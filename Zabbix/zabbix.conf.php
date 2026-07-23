<?php
// Zabbix GUI configuration file.
$DB['TYPE']                 = 'POSTGRESQL';
$DB['SERVER']               = '127.0.0.1';
$DB['PORT']                 = '0';
$DB['DATABASE']             = 'zabbix';
$DB['USER']                 = 'zabbix';
$DB['PASSWORD']             = '<MASKED_PASSWORD>';
// Schema name. Used for PostgreSQL.
$DB['SCHEMA']               = '';
// Used for TLS connection.
$DB['ENCRYPTION']           = false;
$DB['KEY_FILE']             = '';
$DB['CERT_FILE']            = '';
$DB['CA_FILE']              = '';
$DB['VERIFY_HOST']          = false;
$DB['CIPHER_LIST']          = '';
// Vault configuration. Used if database credentials are stored in Vault secrets manager.
$DB['VAULT']                = '';
$DB['VAULT_URL']            = '';
$DB['VAULT_PREFIX']         = '';
$DB['VAULT_DB_PATH']        = '';
$DB['VAULT_TOKEN']          = '';
$DB['VAULT_CERT_FILE']      = '';
$DB['VAULT_KEY_FILE']       = '';
// $DB['VAULT_CACHE']       = true;
// $ZBX_SERVER              = '';
// $ZBX_SERVER_PORT         = '';
$ZBX_SERVER_NAME            = '<MASKED_SERVER_NAME>';
$IMAGE_FORMAT_DEFAULT       = IMAGE_FORMAT_PNG;