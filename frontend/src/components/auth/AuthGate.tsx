import { type ReactNode, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { logout, useAuthStatus, useLogin, useMe, useSetup } from '@/api/hooks/auth'
import { AuthContext } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { t } from '@/lib/i18n'
import { RingLogo } from '@/components/RingLogo'

function CenteredCard({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RingLogo size={36} />
            {title}
          </CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>
    </div>
  )
}

function SetupScreen() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const setup = useSetup()

  return (
    <CenteredCard title="Nazgarr" description={t('auth.setupDescription')}>
      <form
        className="grid gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          setup.mutate(
            { username, password },
            { onError: (error) => toast.error(t('auth.creationFailed', { message: error.message })) },
          )
        }}
      >
        <div className="grid gap-1.5">
          <Label htmlFor="setup-username">{t('auth.username')}</Label>
          <Input id="setup-username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="setup-password">{t('auth.password')}</Label>
          <Input
            id="setup-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t('auth.passwordMinChars')}
          />
        </div>
        <Button type="submit" disabled={!username || password.length < 8 || setup.isPending}>
          {t('auth.createAccount')}
        </Button>
      </form>
    </CenteredCard>
  )
}

function LoginScreen() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useLogin()

  return (
    <CenteredCard title="Nazgarr" description={t('auth.loginDescription')}>
      <form
        className="grid gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          login.mutate(
            { username, password },
            { onError: () => toast.error(t('auth.invalidCredentialsToast')) },
          )
        }}
      >
        <div className="grid gap-1.5">
          <Label htmlFor="login-username">{t('auth.username')}</Label>
          <Input id="login-username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="login-password">{t('auth.password')}</Label>
          <Input id="login-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <Button type="submit" disabled={!username || !password || login.isPending}>
          {t('auth.signIn')}
        </Button>
      </form>
    </CenteredCard>
  )
}

export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const { data: status, isPending: statusPending } = useAuthStatus()
  const { data: me, isPending: mePending, isError: meError } = useMe(status?.configured === true)

  if (statusPending) return null
  if (!status?.configured) return <SetupScreen />
  if (mePending) return null
  if (meError || !me) return <LoginScreen />

  return (
    <AuthContext.Provider value={{ username: me.username, logout: () => logout(queryClient) }}>
      {children}
    </AuthContext.Provider>
  )
}
