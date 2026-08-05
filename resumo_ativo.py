# -*- coding: utf-8 -*-
"""
resumo_ativo.py
================
Gera o resumo (estilo WhatsApp) do Relatório Ativo a partir do PDF usando a API
do Claude e envia por e-mail (corpo HTML) e/ou WhatsApp (Z-API).

Fluxo típico (com revisão humana antes do envio):

    from resumo_ativo import gerar_resumo, resumo_para_html, enviar_whatsapp_grupo

    resumo = gerar_resumo(pdf_tijolo, tipo="tijolo")   # gera e retorna o texto
    print(resumo)                                       # <-- confira / edite aqui
    # ... só depois disso rodar os envios (e-mail e WhatsApp)

As credenciais vêm do .env: CLAUDE_API, INSTANCE_ID, TOKEN_Z, CLIENT_TOKEN,
GRUPO_ATIVO_PHONE.
"""

import os
import re
import html
import time
import base64
import random
import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURAÇÕES
# ============================================================
ANTHROPIC_API_KEY = os.getenv("CLAUDE_API")
MODELO_CLAUDE     = "claude-opus-4-8"

# Status transitórios da API do Claude (sobrecarga, rate limit, instabilidade).
# 529 = overloaded_error: nada a ver com créditos, só capacidade momentânea.
_STATUS_RETRIAVEIS = {408, 409, 429, 500, 502, 503, 504, 529}

_cliente_claude = None


def _cliente():
    """Cliente Anthropic (criado sob demanda para não quebrar o import sem .env).

    `max_retries` faz o próprio SDK retentar 429/5xx com backoff exponencial
    antes de levantar a exceção; o laço de `gerar_resumo` cuida das esperas longas.
    """
    global _cliente_claude
    if _cliente_claude is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError("CLAUDE_API não definido no .env.")
        _cliente_claude = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY,
            max_retries=4,
            timeout=600.0,
        )
    return _cliente_claude

# Z-API
ZAPI_INSTANCE_ID  = os.getenv("INSTANCE_ID")
ZAPI_TOKEN        = os.getenv("TOKEN_Z")
ZAPI_CLIENT_TOKEN = os.getenv("CLIENT_TOKEN")
GRUPO_ATIVO_PHONE = os.getenv("GRUPO_ATIVO_PHONE")   # grupo do relatório diário (formato: <id>-group)

_BASE_ZAPI = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}"


# ============================================================
# PROMPTS
# ============================================================
# Regras compartilhadas entre Tijolo e Papel (formatação + precisão).
_REGRAS_COMUNS = (
    "REGRAS DE FORMATAÇÃO (WhatsApp):\n"
    "- Use os emojis de seção exatamente como no modelo de formato indicado no prompt.\n"
    "- Negrito com *asteriscos simples* (padrão WhatsApp).\n"
    "- Números no padrão brasileiro (vírgula decimal, ponto de milhar; use 'milhões' ou 'mi' conforme o modelo).\n"
    "- Sinal de variação: 🟢 positiva, 🔻 negativa, ➡️ (ou ➖) praticamente zero.\n\n"
    "LIMITES DE TAMANHO (OBRIGATÓRIOS):\n"
    "- Qualquer bloco em prosa (manchete e destaques) tem NO MÁXIMO 5 linhas. Nunca ultrapasse isso.\n\n"
    "REGRAS DE PRECISÃO:\n"
    "- Use SOMENTE dados presentes no PDF. Não invente, não arredonde além do exibido, não some manualmente.\n"
    "- Para variações dia-a-dia use as próprias colunas de variação do PDF (VARD dos ativos, VAR|DI30(bps), "
    "VAR|NTNB30(bps), VAR|IBOV, VAR|USD, VAR|IFIX e os bps por vértice na tabela DIs+NTNBs). NÃO afirme valores "
    "absolutos nem sequências do dia anterior (nº de cotistas de ontem, saldo/VARD de ontem, 'X pregões seguidos "
    "de queda/alta', 'máxima/mínima do período') a menos que estejam EXPLÍCITOS no PDF — se não estiverem, "
    "descreva apenas o que o PDF mostra, sem comparação inventada.\n"
    "- Se um dado estiver ilegível, escreva '[ilegível]' em vez de adivinhar.\n"
    "- Nunca mencione revisões, correções, versões anteriores ou mudanças de valores. Entregue o resultado "
    "final direto, como primeira e única análise.\n"
    "- Responda sempre em português brasileiro.\n"
    "- O primeiro caractere da resposta deve ser o emoji 📅 do cabeçalho. Não escreva nada antes dele.\n"
)

PROMPT_RESUMO_TIJOLO = (
    "Você é um analista financeiro especializado em Fundos Imobiliários (FIIs), focado no GARE11.\n\n"
    "Você recebe o PDF do 'RELATÓRIO ATIVO — CENÁRIO DIÁRIO' (foco TIJOLO). O layout tem:\n"
    "- Caixa 'HIGHLIGHTS GARE11': PREÇO(FECH), PREÇO(MAX/MIN), LIQ(MM), SHORT(MM), P/VP, VAR(D), VAR(Week), "
    "VAR(M), DYm, DYa, DY.\n"
    "- Caixa 'HIGHLIGHTS MERCADO': DI(5Y) e VAR|DI30(bps); NTNB(5Y) e VAR|NTNB30(bps); IBOV(MIL) e VAR|IBOV; "
    "USD e VAR|USD; IFIX e VAR|IFIX; rankings de COTISTAS e LIQUIDEZ do GARE11 vs IFIX/Tijolo.\n"
    "- Tabela 'INFORMAÇÕES DIÁRIAS — SETORES | PEERS': cada ativo/categoria com FECH, VARD, VARM, VARdez/24, "
    "VARY, P/VP, VOL(D), VOL(90D), SALDO(short), DYa, DY, VP, COTISTAS, %PL. A 1ª linha é o GARE11.\n"
    "- Tabela 'DIs + NTNBs' e blocos 'PRINCIPAIS ACONTECIMENTOS' e 'FUNDOS EM OFERTA'.\n\n"
    "EXTRAÇÃO (interna, não exiba este raciocínio):\n"
    "1. GARE11: preço FECH, VARD, VAR(Week), VARM, VARdez/24, LIQ(MM) como volume do dia, VOL(90D) como média "
    "de 90 dias, SALDO(short), P/VP e DY (12M).\n"
    "2. Macro: IFIX e VAR|IFIX; DI(5Y) e VAR|DI30(bps); NTNB(5Y) e VAR|NTNB30(bps); IBOV e VAR|IBOV; USD e VAR|USD.\n"
    "3. Peers (coluna VARD): HGRU11, TRXF11, HGLG11, BTLG11, XPLG11, KNRI11.\n"
    "4. Categorias 'Prime' (coluna VARD): HIB Tijolo Prime, Renda Urbana Prime, Logístico Prime, "
    "Shopping Prime, Lajes Prime.\n"
    "5. Fundos em oferta e principais acontecimentos do dia.\n\n"
    "Use a DATA do próprio relatório (ex.: '23/07/2026') no cabeçalho.\n\n"
    "GERE EXATAMENTE ESTE FORMATO (troque os valores pelos do PDF; mantenha as seções e a ordem):\n\n"
    "📅 Resumo Ativo Tijolo – DD/MM/AAAA\n\n"
    "⚠️ <manchete de UMA linha com o fato mais importante do dia para o GARE11/mercado>\n\n"
    "🏢 <parágrafo do GARE11: preço de fechamento e variação diária, volume do dia vs média de 90d, saldo de "
    "short, variação na semana/mês/desde dez-24, P/VP e DY 12M. MÁXIMO 5 LINHAS.>\n\n"
    "❗ <parágrafo macro: IFIX e variação; movimento do DI 5 anos em bps e nível; NTN-B 5 anos em bps e nível; "
    "Ibovespa; dólar. MÁXIMO 5 LINHAS.>\n\n"
    "📌 Resumo do GARE11\n"
    "💰 Preço de Fechamento: R$ X,XX\n"
    "➖ Variação Diária: X,XX%\n"
    "📈 Variação na Semana: X,XX%\n"
    "📈 Variação no Mês: X,XX%\n"
    "📈 Valorização desde dez/24: X,XX%\n"
    "💵 Volume: R$ X,X milhões\n"
    "📈 DY (12M): XX,XX%\n"
    "⚖️ P/VP: X,XX\n\n"
    "📊 Principais Peers do GARE11 (VARD)\n"
    "<emoji> HGRU11: X,XX%\n"
    "<emoji> TRXF11: X,XX%\n"
    "<emoji> HGLG11: X,XX%\n"
    "<emoji> BTLG11: X,XX%\n"
    "<emoji> XPLG11: X,XX%\n"
    "<emoji> KNRI11: X,XX%\n\n"
    "🏗️ Comportamento das categorias \"Prime\" (VARD)\n"
    "<emoji> HIB Tijolo Prime: X,XX%\n"
    "<emoji> Renda Urbana Prime: X,XX%\n"
    "<emoji> Logístico Prime: X,XX%\n"
    "<emoji> Shopping Prime: X,XX%\n"
    "<emoji> Lajes Prime: X,XX%\n\n"
    "🔔 Destaque do Dia: <fato mais relevante do dia>\n\n"
    "ℹ️ Aviso: <fundos em oferta e, se houver, fatos relevantes; caso não haja fato relevante específico do "
    "GARE11, diga isso>\n\n"
    "📌 Movimentos atípicos\n"
    "▸ <bullet>\n\n"
    "REGRA ESPECIAL — MOVIMENTOS ATÍPICOS:\n"
    "- No MÁXIMO 3 bullets.\n"
    "- PRIORIZE movimentos atípicos do PRÓPRIO GARE11 (ex.: salto na base de cotistas, volume muito acima/abaixo "
    "da média de 90d, mudança relevante no saldo de short, descolamento vs peers).\n"
    "- Se o GARE11 NÃO teve nenhum movimento atípico no dia, NÃO invente nem force um destaque sobre ele. "
    "Nesse caso, traga no máximo 1–2 movimentos atípicos gerais do mercado; se também não houver nada relevante, "
    "escreva um único bullet '▸ Sem movimentos atípicos relevantes no pregão.'\n\n"
    + _REGRAS_COMUNS
)

PROMPT_RESUMO_PAPEL = (
    "Você é um analista financeiro especializado em Fundos Imobiliários (FIIs) de PAPEL/crédito (CRI), "
    "focado no GAME11 (Guardian Multiestratégia).\n\n"
    "Você recebe o PDF do 'RELATÓRIO ATIVO FII — CENÁRIO DIÁRIO' (versão PAPEL). O layout tem:\n"
    "- Caixa 'HIGHLIGHTS GAME11': PREÇO(FECH), LIQ(MM), SHORT(MM), P/VP, VAR(D), VAR(Week), VAR(M), DYm, DYa, DY.\n"
    "- Caixa 'HIGHLIGHTS MERCADO': DI(5Y) e VAR|DI30(bps); NTNB(5Y) e VAR|NTNB30(bps); IBOV(MIL) e VAR|IBOV; "
    "USD e VAR|USD; IFIX e VAR|IFIX.\n"
    "- Tabela 'INFORMAÇÕES DIÁRIAS — SETORES | PEERS': categorias de papel (Papel, Fof, Hedge Fund, High Grade, "
    "Middle Grade, High Yield) e tickers, com FECH, VAR(D), VARM etc. A 1ª linha é o GAME11.\n"
    "- Tabela 'DIs + NTNBs' (VARD em bps por vértice: F27..F35, NTNB26..35).\n"
    "- Tabela 'Maiores Altas e Baixas' (tickers com VAR do dia) e blocos 'PRINCIPAIS ACONTECIMENTOS' e "
    "'FUNDOS EM OFERTA'.\n\n"
    "EXTRAÇÃO (interna, não exiba o raciocínio):\n"
    "1. GAME11 (use a CAIXA de highlights do GAME11): PREÇO(FECH), VAR(Week), VAR(M), LIQ(MM) como volume, "
    "DYa (= DY a.a.), DY (= DY 12M) e P/VP. Para a VARIAÇÃO DIÁRIA use a coluna VAR(D) da linha GAME11 da TABELA, "
    "com 2 casas decimais (ex.: -0,12%).\n"
    "2. Macro: DI(5Y) e VAR|DI30(bps); NTNB(5Y) e VAR|NTNB30(bps); IBOV e VAR|IBOV; USD e VAR|USD; IFIX e VAR|IFIX.\n"
    "3. Peers (coluna VAR(D) na tabela): CPTS11, RBRX11, VGHF11, MXRF11, MANA11.\n"
    "4. Setores/categorias (coluna VAR(D)): Hedge Fund, High Grade, Middle Grade, High Yield.\n"
    "5. Maiores altas e baixas do dia (tabela lateral 'Maiores Altas e Baixas').\n"
    "6. Fato relevante do dia (PRINCIPAIS ACONTECIMENTOS) e fundos em oferta.\n\n"
    "Use a DATA do próprio relatório no cabeçalho.\n\n"
    "GERE EXATAMENTE ESTE FORMATO (troque os valores pelos do PDF; mantenha seções, ordem e emojis):\n\n"
    "📅 *Resumo Ativo Papel – DD/MM/AAAA*\n\n"
    "<emoji> *<manchete de UMA linha: direção do GAME11 no dia + principal fato macro. Use 🟢 se GAME11 subiu, "
    "🔻 se caiu, 🟡 se praticamente estável.>*\n\n"
    "📌 *GAME11 | Fechamento*\n"
    "💰 Preço: *R$ X,XX* (*X,XX%*)\n"
    "📈 Semana: *X,X%* | Mês: *X,X%*\n"
    "💵 Volume: *R$ X,XX mi*\n"
    "📊 DY a.a.: *XX,X%* | DY 12M: *XX,X%*\n"
    "⚖️ P/VP: *X,XX*\n\n"
    "🌐 *Macro do dia*\n"
    "▪️ DI 5Y: XX,XX% (*±X,XX bps*) — <comentário curto do movimento, se relevante>\n"
    "▪️ NTN-B 5Y: X,XX% (*±X,XX bps*)\n"
    "▪️ IBOV: *X,X%* | Dólar: *X,X%* (R$ X,XX)\n"
    "▪️ IFIX: *X,XX%* (X.XXX pts)\n\n"
    "📊 *Peers*\n"
    "<emoji> CPTS11: X,XX% | <emoji> RBRX11: X,XX% | <emoji> VGHF11: X,XX%\n"
    "<emoji> MXRF11: X,XX% | <emoji> MANA11: X,XX%\n\n"
    "🏗️ *Setores*\n"
    "<emoji> Hedge Fund: X,XX% | <emoji> High Grade: X,XX%\n"
    "<emoji> Middle Grade: X,XX% | <emoji> High Yield: X,XX%\n\n"
    "⚡ *Destaques do dia*\n"
    "<emoji do GAME11> *<destaque do GAME11: variação do dia e comparação com os peers do dia. MÁX. 5 LINHAS.>*\n\n"
    "📉 *<destaque de juros/DI: magnitude do movimento em bps, vértices mais fortes (tabela DIs+NTNBs) e nível "
    "resultante. MÁX. 5 LINHAS.>*\n\n"
    "📰 *<fato relevante do dia, se houver em PRINCIPAIS ACONTECIMENTOS; se não houver, omita esta linha>*\n\n"
    "📊 *<maiores altas e baixas do dia: a maior alta e a(s) maior(es) baixa(s), com os %>*\n\n"
    "REGRAS ESPECIAIS — DESTAQUES:\n"
    "- Priorize o GAME11 no primeiro destaque. Se o GAME11 não teve nada atípico, apenas descreva a variação do "
    "dia, sem forçar narrativa nem inventar comparação com dias anteriores (ver regras de precisão).\n\n"
    + _REGRAS_COMUNS
)

_PROMPTS = {"tijolo": PROMPT_RESUMO_TIJOLO, "papel": PROMPT_RESUMO_PAPEL}


# ============================================================
# GERAÇÃO DO RESUMO (Claude API)
# ============================================================
def gerar_resumo(pdf_path, tipo="tijolo", max_tokens=2048, tentativas=5, espera_inicial=20):
    """Lê o PDF em `pdf_path`, envia ao Claude e retorna o texto do resumo.

    tipo: "tijolo" ou "papel".
    tentativas / espera_inicial: em caso de sobrecarga (529) ou instabilidade,
    reenvia a requisição com backoff exponencial (20s, 40s, 80s, 120s...).
    Retorna a string do resumo, ou None em caso de erro.
    """
    tipo = tipo.lower()
    if tipo not in _PROMPTS:
        raise ValueError(f"tipo inválido: {tipo!r}. Use 'tijolo' ou 'papel'.")

    print(f"🤖 Gerando resumo ({tipo}) com o Claude a partir de:\n   {pdf_path}")

    with open(pdf_path, "rb") as f:
        pdf_base64 = base64.standard_b64encode(f.read()).decode("utf-8")

    conteudo = [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_base64,
            },
        },
        {
            "type": "text",
            "text": "Gere o resumo do relatório em anexo seguindo rigorosamente o formato especificado.",
        },
    ]

    for tentativa in range(1, tentativas + 1):
        try:
            resposta = _cliente().messages.create(
                model=MODELO_CLAUDE,
                max_tokens=max_tokens,
                system=_PROMPTS[tipo],
                messages=[{"role": "user", "content": conteudo}],
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            detalhe = getattr(e, "message", None) or str(e)
            retriavel = status is None or status in _STATUS_RETRIAVEIS
            if retriavel and tentativa < tentativas:
                espera = min(espera_inicial * 2 ** (tentativa - 1), 120) + random.uniform(0, 3)
                motivo = "sobrecarregada (529)" if status == 529 else f"indisponível ({status or 'conexão'})"
                print(f"⚠️  API do Claude {motivo}. Tentativa {tentativa}/{tentativas} — "
                      f"nova tentativa em {espera:.0f}s...")
                time.sleep(espera)
                continue
            print(f"❌ Erro na API do Claude: {status or 'conexão'} - {detalhe}")
            return None

        resumo = "".join(b.text for b in resposta.content if b.type == "text")
        if resposta.stop_reason == "max_tokens":
            print(f"⚠️  Resposta truncada (max_tokens={max_tokens}). "
                  f"Rode de novo com max_tokens maior.")
        print("✅ Resumo gerado.")
        return resumo

    print(f"❌ API do Claude segue sobrecarregada após {tentativas} tentativas. Tente novamente em alguns minutos.")
    return None


# ============================================================
# CONVERSÃO PARA CORPO DE E-MAIL (HTML)
# ============================================================
def resumo_para_html(resumo, saudacao=None):
    """Converte o texto do resumo (estilo WhatsApp) em corpo HTML para e-mail,
    preservando negrito (*...*), separadores (---) e quebras de linha.
    """
    corpo = html.escape(resumo)
    linhas = []
    for linha in corpo.split("\n"):
        if linha.strip() and set(linha.strip()) <= {"-"} and len(linha.strip()) >= 3:
            linhas.append("<hr style='border:none;border-top:1px solid #dddddd;margin:12px 0;'>")
        else:
            linhas.append(linha)
    corpo = "\n".join(linhas)
    # negrito do WhatsApp: *texto* -> <b>texto</b>
    corpo = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", corpo)
    # quebras de linha -> <br>, mas não logo antes/depois de <hr>
    corpo = corpo.replace("\n", "<br>\n").replace("<br>\n<hr", "<hr").replace("</hr><br>", "</hr>")

    saudacao_html = f"<p>{html.escape(saudacao)}</p>" if saudacao else ""
    return (
        "<html><body style=\"font-family: Arial, sans-serif; font-size: 14px; "
        "color: #222222; line-height: 1.55;\">"
        f"{saudacao_html}"
        f"<div>{corpo}</div>"
        "</body></html>"
    )


# ============================================================
# ENVIO WHATSAPP (Z-API) — texto do resumo + PDF como documento
# ============================================================
def _headers_zapi():
    return {"Client-Token": ZAPI_CLIENT_TOKEN, "Content-Type": "application/json"}


def enviar_texto_whatsapp(mensagem, phone=None):
    phone = phone or GRUPO_ATIVO_PHONE
    r = requests.post(
        f"{_BASE_ZAPI}/send-text",
        headers=_headers_zapi(),
        json={"phone": phone, "message": mensagem},
    )
    if r.status_code == 200:
        print(f"✅ Texto enviado ao WhatsApp ({phone}). messageId: {r.json().get('messageId')}")
    else:
        print(f"❌ Erro send-text Z-API: {r.status_code} - {r.text}")
    return r


def enviar_documento_whatsapp(pdf_path, phone=None, caption=None):
    phone = phone or GRUPO_ATIVO_PHONE
    with open(pdf_path, "rb") as f:
        pdf_base64 = base64.standard_b64encode(f.read()).decode("utf-8")
    payload = {
        "phone": phone,
        "document": f"data:application/pdf;base64,{pdf_base64}",
        "fileName": os.path.basename(pdf_path),
    }
    if caption:
        payload["caption"] = caption
    r = requests.post(
        f"{_BASE_ZAPI}/send-document/pdf",
        headers=_headers_zapi(),
        json=payload,
    )
    if r.status_code == 200:
        print(f"✅ PDF enviado ao WhatsApp ({phone}). messageId: {r.json().get('messageId')}")
    else:
        print(f"❌ Erro send-document Z-API: {r.status_code} - {r.text}")
    return r


def enviar_whatsapp_grupo(resumo, pdf_path, phone=None):
    """Envia o resumo (texto) e, em seguida, o PDF (documento) para o grupo."""
    phone = phone or GRUPO_ATIVO_PHONE
    if not phone:
        raise ValueError("GRUPO_ATIVO_PHONE não definido no .env (e nenhum phone passado).")
    enviar_texto_whatsapp(resumo, phone=phone)
    enviar_documento_whatsapp(pdf_path, phone=phone)


# ============================================================
# HELPER — listar grupos para descobrir o ID (GRUPO_ATIVO_PHONE)
# ============================================================
def listar_grupos_whatsapp(page=1, page_size=100):
    """Lista os grupos da instância (nome + phone). Use o campo `phone`
    (formato '<id>-group') como GRUPO_ATIVO_PHONE no .env.
    """
    r = requests.get(
        f"{_BASE_ZAPI}/groups",
        headers={"Client-Token": ZAPI_CLIENT_TOKEN},
        params={"page": page, "pageSize": page_size},
    )
    if r.status_code != 200:
        print(f"❌ Erro ao listar grupos: {r.status_code} - {r.text}")
        return []
    grupos = r.json()
    for g in grupos:
        print(f"- {g.get('name')!r:40} phone={g.get('phone')}")
    print(f"\n{len(grupos)} grupo(s) na página {page}.")
    return grupos
