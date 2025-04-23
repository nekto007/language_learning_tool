#!/bin/sh

postconf -e "myhostname = mail.llt-english.com"
postconf -e "mydomain = llt-english.com"
postconf -e "myorigin = /etc/mailname"
echo "llt-english.com" > /etc/mailname

postconf -e "mydestination = "
postconf -e "relayhost = "
postconf -e "inet_interfaces = all"
postconf -e "inet_protocols = ipv4"

postconf -e "smtpd_tls_cert_file=/etc/letsencrypt/live/llt-english.com/fullchain.pem"
postconf -e "smtpd_tls_key_file=/etc/letsencrypt/live/llt-english.com/privkey.pem"
postconf -e "smtpd_use_tls=yes"
postconf -e "smtp_tls_security_level = may"
postconf -e "smtp_tls_note_starttls_offer = yes"

touch /var/log/mail.log
rsyslogd
postfix start
tail -F /var/log/mail.log

exec /usr/sbin/postfix start-fg