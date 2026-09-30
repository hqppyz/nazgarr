export const auth = {
  'auth.setupDescription': 'Create the administrator account — a single user, never basic auth.',
  'auth.loginDescription': 'Sign in to continue.',
  'auth.username': 'Username',
  'auth.password': 'Password',
  'auth.passwordMinChars': 'At least 8 characters',
  'auth.createAccount': 'Create account',
  'auth.setupCode': 'Setup code',
  'auth.setupCodeHelp':
    'Printed in the container log at startup (e.g. docker logs nazgarr). It proves you run this instance: nobody else on your network can create the account.',
  'auth.signIn': 'Sign in',
  'auth.creationFailed': 'Account creation failed: {message}',
  'auth.invalidCredentialsToast': 'Invalid credentials.',
} as const
