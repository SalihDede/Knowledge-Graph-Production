import { useEffect, useState } from 'react'

async function authRequest(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || response.statusText)
  }
  return data
}

export default function AuthPanel({ open, onClose, identity, onIdentityChange, t }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setError('')
    setPassword('')
  }, [open, mode])

  if (!open) return null

  async function handleSubmit(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      const path = mode === 'register' ? '/api/auth/register' : '/api/auth/login'
      const body = mode === 'register'
        ? { email, password, display_name: displayName }
        : { email, password }
      const nextIdentity = await authRequest(path, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onIdentityChange(nextIdentity)
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
    } finally {
      setLoading(false)
    }
  }

  async function handleLogout() {
    setLoading(true)
    setError('')
    try {
      const nextIdentity = await authRequest('/api/auth/logout', { method: 'POST' })
      onIdentityChange(nextIdentity)
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-overlay" role="presentation" onMouseDown={onClose}>
      <section
        className="auth-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
        onMouseDown={event => event.stopPropagation()}
      >
        <button className="auth-close" type="button" onClick={onClose} aria-label={t.auth.close}>×</button>

        {identity?.authenticated ? (
          <div className="auth-account-view">
            <span className="auth-kicker">{t.auth.account}</span>
            <div className="auth-avatar" aria-hidden="true">
              {identity.user.display_name.slice(0, 1).toUpperCase()}
            </div>
            <h2 id="auth-title">{identity.user.display_name}</h2>
            <p>{identity.user.email}</p>
            <span className={`auth-verification ${identity.user.email_verified ? 'verified' : ''}`}>
              {identity.user.email_verified ? t.auth.verified : t.auth.verificationPending}
            </span>
            {error && <p className="auth-error" role="alert">{error}</p>}
            <button className="auth-secondary-button" type="button" disabled={loading} onClick={handleLogout}>
              {loading ? t.auth.working : t.auth.logout}
            </button>
          </div>
        ) : (
          <>
            <span className="auth-kicker">{t.auth.anonymousFirst}</span>
            <h2 id="auth-title">{mode === 'register' ? t.auth.createAccount : t.auth.login}</h2>
            <p className="auth-description">{t.auth.guestDescription}</p>

            <div className="auth-mode-switch" role="group" aria-label={t.auth.modeAria}>
              <button
                className={mode === 'login' ? 'active' : ''}
                type="button"
                onClick={() => setMode('login')}
              >
                {t.auth.login}
              </button>
              <button
                className={mode === 'register' ? 'active' : ''}
                type="button"
                onClick={() => setMode('register')}
              >
                {t.auth.register}
              </button>
            </div>

            <form className="auth-form" onSubmit={handleSubmit}>
              {mode === 'register' && (
                <label>
                  <span>{t.auth.displayName}</span>
                  <input
                    value={displayName}
                    onChange={event => setDisplayName(event.target.value)}
                    autoComplete="name"
                    minLength={2}
                    maxLength={120}
                    required
                  />
                </label>
              )}
              <label>
                <span>{t.auth.email}</span>
                <input
                  type="email"
                  value={email}
                  onChange={event => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                />
              </label>
              <label>
                <span>{t.auth.password}</span>
                <input
                  type="password"
                  value={password}
                  onChange={event => setPassword(event.target.value)}
                  autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                  minLength={mode === 'register' ? 10 : 1}
                  maxLength={128}
                  required
                />
              </label>
              {mode === 'register' && <small>{t.auth.passwordHint}</small>}
              {error && <p className="auth-error" role="alert">{error}</p>}
              <button className="auth-submit" type="submit" disabled={loading}>
                {loading
                  ? t.auth.working
                  : mode === 'register' ? t.auth.createAccount : t.auth.login}
              </button>
            </form>
          </>
        )}
      </section>
    </div>
  )
}
