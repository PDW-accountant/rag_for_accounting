import { Component, StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

/** 렌더 크래시 시 흰 화면 대신 복구 안내를 보여주는 최후 방어선. */
class AppErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error: unknown) {
    console.error('렌더링 오류:', error)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="fatal-error" role="alert">
          <p>화면을 그리는 중 문제가 발생했습니다. 새로고침 후 다시 시도해 주세요.</p>
          <button onClick={() => window.location.reload()}>새로고침</button>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
)
