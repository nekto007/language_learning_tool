#!/bin/sh

postconf -e "myhostname = mail.llt-english.com"
postconf -e "mydomain = llt-english.com"
postconf -e "myorigin = /etc/mailname"
echo "llt-english.com" > /etc/mailname

postconf -e "mydestination = "
postconf -e "relayhost = "
postconf -e "inet_interfaces = all"
postconf -e "inet_protocols = ipv4"
postconf -e "mynetworks = 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16"
postconf -e "smtpd_relay_restrictions = permit_mynetworks, reject_unauth_destination"
postconf -e "smtpd_recipient_restrictions = permit_mynetworks, reject_unauth_destination"

postconf -e "smtpd_tls_cert_file=/etc/letsencrypt/live/llt-english.com/fullchain.pem"
postconf -e "smtpd_tls_key_file=/etc/letsencrypt/live/llt-english.com/privkey.pem"
postconf -e "smtpd_use_tls=yes"
postconf -e "smtp_tls_security_level = may"
postconf -e "smtp_tls_note_starttls_offer = yes"

# OpenDKIM milter configuration
postconf -e "milter_protocol = 6"
postconf -e "milter_default_action = accept"
postconf -e "smtpd_milters = inet:opendkim:8891"
postconf -e "non_smtpd_milters = inet:opendkim:8891"

postfix start-fg
