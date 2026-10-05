import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts'

import type { Schemas } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { dailyHealth, healthLabel } from '@/lib/health'
import { t } from '@/lib/i18n'

type HistoryPoint = Schemas['HistoryPoint']

// L'andamento della salute nella dashboard: caricato a parte (recharts).
function formatDay(value: number) {
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function HistoryChart({ history, current }: { history: HistoryPoint[] | undefined; current: number }) {
  const chartData = dailyHealth(history ?? [])
  const min = Math.min(...chartData.map((d) => d.health), 100)
  const chartConfig = {
    health: { label: t('dashboard.healthHistory'), color: healthLabel(current).color },
  } satisfies ChartConfig
  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle>{t('dashboard.healthHistory')}</CardTitle>
      </CardHeader>
      <CardContent className="px-2 sm:px-6">
        {chartData.length < 2 ? (
          <p className="text-sm text-muted-foreground">{t('dashboard.notEnoughHistory')}</p>
        ) : (
          <ChartContainer config={chartConfig} className="aspect-auto h-[180px] w-full sm:h-[260px]">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="fillHealth" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-health)" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="var(--color-health)" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis
                dataKey="day"
                type="number"
                scale="time"
                domain={['dataMin', 'dataMax']}
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={32}
                tickFormatter={formatDay}
              />
              <YAxis
                domain={[Math.max(0, Math.floor(min / 10) * 10 - 10), 100]}
                tickLine={false}
                axisLine={false}
                width={32}
                tickCount={4}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(_value, payload) => formatDay(Number(payload?.[0]?.payload?.day))}
                    indicator="dot"
                  />
                }
              />
              <Area dataKey="health" type="monotone" fill="url(#fillHealth)" stroke="var(--color-health)" />
            </AreaChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}
