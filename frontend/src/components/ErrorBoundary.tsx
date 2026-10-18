import { Component, type ErrorInfo, type ReactNode } from 'react'

// Senza un confine, un errore durante il render (o un chunk che non si
// scarica più dopo un aggiornamento) smonta tutta l'app: pagina bianca,
// nessun messaggio. Qui l'errore si ferma e al suo posto c'è `fallback`.
// `resetKey` cambiato (es. la pagina aperta) riprova da capo.
interface Props {
  fallback: (props: { error: Error; reset: () => void }) => ReactNode
  resetKey?: unknown
  children: ReactNode
}

interface State {
  error: Error | null
  resetKey: unknown
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey }

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error: error instanceof Error ? error : new Error(String(error)) }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.resetKey ? { error: null, resetKey: props.resetKey } : null
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack)
  }

  reset = () => this.setState({ error: null })

  render() {
    if (this.state.error) return this.props.fallback({ error: this.state.error, reset: this.reset })
    return this.props.children
  }
}
