import { useState } from 'react'
import { toast } from 'sonner'

import { useChangePassword, useLogoutEverywhere } from '@/api/hooks/auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/contexts/AuthContext'
import { t } from '@/lib/i18n'

export function SecuritySection() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const changePassword = useChangePassword()
  const logoutEverywhere = useLogoutEverywhere()
  const { username } = useAuth()

  const mismatch = newPassword.length > 0 && confirmPassword.length > 0 && newPassword !== confirmPassword

  function submit() {
    changePassword.mutate(
      { current_password: currentPassword, new_password: newPassword, username: username ?? '' },
      {
        onSuccess: () => {
          toast.success(t('security.passwordChanged'))
          setCurrentPassword('')
          setNewPassword('')
          setConfirmPassword('')
        },
        onError: (error) => toast.error(t('common.saveFailed', { message: error.message })),
      },
    )
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t('security.title')}</CardTitle>
          <CardDescription>{t('security.description')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="sec-current">{t('security.currentPassword')}</Label>
            <Input
              id="sec-current"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="sec-new">{t('security.newPassword')}</Label>
            <Input id="sec-new" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="sec-confirm">{t('security.confirmPassword')}</Label>
            <Input
              id="sec-confirm"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
            {mismatch && <p className="text-xs text-destructive">{t('security.passwordsDontMatch')}</p>}
          </div>
          <div>
            <Button
              onClick={submit}
              disabled={
                !currentPassword || !newPassword || newPassword !== confirmPassword || changePassword.isPending
              }
            >
              {t('security.changePassword')}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t('security.changePasswordRevokes')}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('security.sessionsTitle')}</CardTitle>
          <CardDescription>{t('security.sessionsDescription')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" disabled={logoutEverywhere.isPending} onClick={() => logoutEverywhere.mutate()}>
            {t('security.logoutEverywhere')}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('security.twoFactorTitle')}</CardTitle>
          <CardDescription>{t('security.twoFactorDescription')}</CardDescription>
        </CardHeader>
      </Card>
    </>
  )
}
