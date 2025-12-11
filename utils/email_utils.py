import smtplib
from email.message import EmailMessage

def send_reset_email(to_email: str):
    msg = EmailMessage()
    msg['Subject'] = 'Password Reset Request'
    msg['From'] = 'johnvesly007@gmail.com'  # Replace with your Gmail
    msg['To'] = to_email

    msg.set_content(f"""
    Hi,

    We received a request to reset your password.
    Click the link below to reset your password:
    https://yourdomain.com/reset-password?email={to_email}

    If you didn't request this, please ignore this email.

    Thanks,
    YourApp Team
    """)

    # Login and send email using Gmail SMTP
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login('johnvesly007@gmail.com', 'zzdd aujk nwxz tngk')
            smtp.send_message(msg)
            print("Reset email sent successfully.")
    except Exception as e:
        print(f"Error sending email: {e}")
