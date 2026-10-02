export const auth = {
  'auth.setupDescription': 'Crea l’account amministratore: un solo utente, mai basic auth.',
  'auth.loginDescription': 'Accedi per continuare.',
  'auth.username': 'Nome utente',
  'auth.password': 'Password',
  'auth.passwordMinChars': 'Almeno 8 caratteri',
  'auth.createAccount': 'Crea account',
  'auth.setupCode': 'Codice di configurazione',
  'auth.setupCodeHelp':
    'Stampato nel log del container all’avvio (es. docker logs nazgarr). Dimostra che sei tu a gestire questa istanza: nessun altro sulla tua rete può creare l’account.',
  'auth.signIn': 'Accedi',
  'auth.creationFailed': 'Creazione dell’account non riuscita: {message}',
  'auth.invalidCredentialsToast': 'Credenziali non valide.',
} as const
