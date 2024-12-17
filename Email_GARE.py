import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

def send_email_with_pdf(pdf_path):
    # Configurações do remetente e destinatários
    sender_email = 'lc@guardian-asset.com'  # Substitua pelo seu e-mail
    sender_password = 'wwafykwsxuhslwwv'  # Substitua pela sua senha ou senha de aplicativo
    recipient_email = ['lc@guardian-asset.com', 'pmk@guardian-asset.com', 'msf@guardian-asset.com','cm@guardian-asset.com','lb@guardian-asset.com','ja@guardian-asset.com','gsa@guardian-asset.com', 
                       'js@guardian-asset.com','rg@guardian-asset.com','gvm@guardian-asset.com','tcs@guardian-asset.com', 'rt@guardian-asset.com','acl@guardian-asset.com']  # Lista de destinatários

    # Criando a mensagem
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = ", ".join(recipient_email)
    msg['Subject'] = "RELATÓRIO DE PASSIVO GARE DIA 11.12.2024"

    # Corpo do e-mail
    body = "Prezados, segue relatório do passivo do GARE do dia 11.12.2024"
    msg.attach(MIMEText(body, 'plain'))

    # Anexar o arquivo PDF
    try:
        with open(pdf_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())

        # Codificar o arquivo em Base64
        encoders.encode_base64(part)

        # Adicionar cabeçalhos para o anexo
        part.add_header(
            "Content-Disposition",
            f"attachment; filename= {os.path.basename(pdf_path)}",  # Nome do arquivo
        )

        # Anexar o arquivo PDF à mensagem
        msg.attach(part)

    except Exception as e:
        print(f"Falha ao anexar o arquivo: {e}")
        return

    # Conectar ao servidor SMTP do Gmail e enviar o e-mail
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp_server:
            smtp_server.login(sender_email, sender_password)
            smtp_server.sendmail(sender_email, recipient_email, msg.as_string())

        print(f"E-mail enviado para {', '.join(recipient_email)}")

    except Exception as e:
        print(f"Falha ao enviar e-mail: {e}")

# Exemplo de uso da função
send_email_with_pdf(r"c:\Users\LucasCavalcante\Desktop\RELATÓRIOS\PASSIVO\GARE\Passivos_GARE11_11.12.2024.pdf")