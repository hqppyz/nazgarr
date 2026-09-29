import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ServiceLogo } from '@/components/ServiceLogo'
import { SettingField } from '@/components/SettingField'
import { t } from '@/lib/i18n'

export function MetadataSection() {
  return (
    <>
      <Card>
        <CardHeader className="flex flex-row gap-3">
          <ServiceLogo src="/logos/tmdb.svg" alt="TMDB" />
          <div>
            <CardTitle>{t('metadata.tmdbTitle')}</CardTitle>
            <CardDescription>{t('metadata.tmdbDescription')}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <SettingField
            settingKey="tmdb_api_key"
            label={t('metadata.apiKey')}
            description={t('metadata.tmdbApiKeyDescription')}
            type="password"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row gap-3">
          <ServiceLogo src="/logos/tvdb.svg" alt="TVDB" />
          <div>
            <CardTitle>{t('metadata.tvdbTitle')}</CardTitle>
            <CardDescription>{t('metadata.tvdbDescription')}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <SettingField
            settingKey="tvdb_api_key"
            label={t('metadata.apiKey')}
            description={t('metadata.tvdbApiKeyDescription')}
            type="password"
          />
        </CardContent>
      </Card>
    </>
  )
}
