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
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || response.statusText)
  }
  return data
}

function AccountSessions({ t, setError }) {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)

  async function load() {
    setLoading(true)
    try {
      const data = await authRequest('/api/auth/sessions')
      setSessions(data || [])
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleRevoke(sessionId) {
    setBusyId(sessionId)
    try {
      await authRequest(`/api/auth/sessions/${sessionId}`, { method: 'DELETE' })
      setSessions(prev => prev.filter(session => session.id !== sessionId))
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
    } finally {
      setBusyId(null)
    }
  }

  async function handleRevokeAllOthers() {
    setBusyId('all')
    try {
      await authRequest('/api/auth/sessions', { method: 'DELETE' })
      await load()
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="auth-sessions">
      <h3>{t.auth.sessionsTitle}</h3>
      {loading && <p className="auth-hint">{t.auth.sessionsLoading}</p>}
      {!loading && sessions.length === 0 && <p className="auth-hint">{t.auth.sessionsEmpty}</p>}
      {!loading && sessions.length > 0 && (
        <ul className="auth-session-list">
          {sessions.map(session => (
            <li key={session.id} className="auth-session-item">
              <div>
                <strong>{session.is_current ? t.auth.sessionCurrent : new Date(session.created_at).toLocaleString()}</strong>
                <small>{new Date(session.last_seen_at).toLocaleString()}</small>
              </div>
              {!session.is_current && (
                <button
                  type="button"
                  className="auth-secondary-button auth-session-revoke"
                  disabled={busyId === session.id}
                  onClick={() => handleRevoke(session.id)}
                >
                  {t.auth.sessionRevoke}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {sessions.length > 1 && (
        <button
          type="button"
          className="auth-secondary-button"
          disabled={busyId === 'all'}
          onClick={handleRevokeAllOthers}
        >
          {t.auth.sessionsRevokeAllOthers}
        </button>
      )}
    </div>
  )
}

function AccountView({ identity, onIdentityChange, onClose, t }) {
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [verificationRequested, setVerificationRequested] = useState(false)
  const [verificationToken, setVerificationToken] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deletePassword, setDeletePassword] = useState('')

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

  async function handleRequestVerification() {
    setLoading(true)
    setError('')
    try {
      await authRequest('/api/auth/email/verification/request', { method: 'POST' })
      setVerificationRequested(true)
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirmVerification(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await authRequest('/api/auth/email/verification/confirm', {
        method: 'POST',
        body: JSON.stringify({ token: verificationToken }),
      })
      const me = await authRequest('/api/auth/me')
      onIdentityChange(me)
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
    } finally {
      setLoading(false)
    }
  }

  async function handleDeleteAccount(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      const nextIdentity = await authRequest('/api/auth/account', {
        method: 'DELETE',
        body: JSON.stringify({ password: deletePassword }),
      })
      onIdentityChange(nextIdentity || { authenticated: false, visitor_id: identity.visitor_id, user: null })
      onClose()
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
      setLoading(false)
    }
  }

  return (
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

      {!identity.user.email_verified && (
        <div className="auth-verification-panel">
          {!verificationRequested ? (
            <button className="auth-secondary-button" type="button" disabled={loading} onClick={handleRequestVerification}>
              {t.auth.sendVerification}
            </button>
          ) : (
            <>
              <p className="auth-hint">{t.auth.verificationSent}</p>
              <form className="auth-inline-form" onSubmit={handleConfirmVerification}>
                <label>
                  <span>{t.auth.verificationTokenLabel}</span>
                  <input
                    value={verificationToken}
                    onChange={event => setVerificationToken(event.target.value)}
                    required
                  />
                </label>
                <button className="auth-secondary-button" type="submit" disabled={loading}>
                  {t.auth.confirmVerification}
                </button>
              </form>
            </>
          )}
        </div>
      )}

      {error && <p className="auth-error" role="alert">{error}</p>}

      <button className="auth-secondary-button" type="button" disabled={loading} onClick={handleLogout}>
        {loading ? t.auth.working : t.auth.logout}
      </button>

      <AccountSessions t={t} setError={setError} />

      <div className="auth-danger-zone">
        <h3>{t.auth.dangerZoneTitle}</h3>
        {!deleteOpen ? (
          <button className="auth-danger-button" type="button" onClick={() => setDeleteOpen(true)}>
            {t.auth.deleteAccount}
          </button>
        ) : (
          <form className="auth-inline-form" onSubmit={handleDeleteAccount}>
            <p className="auth-hint">{t.auth.deleteAccountDescription}</p>
            <label>
              <span>{t.auth.deleteAccountConfirmLabel}</span>
              <input
                type="password"
                value={deletePassword}
                onChange={event => setDeletePassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <div className="auth-danger-actions">
              <button className="auth-danger-button" type="submit" disabled={loading}>
                {t.auth.deleteAccountSubmit}
              </button>
              <button
                className="auth-secondary-button"
                type="button"
                onClick={() => { setDeleteOpen(false); setDeletePassword('') }}
              >
                {t.auth.deleteAccountCancel}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

export default function AuthPanel({ open, onClose, identity, onIdentityChange, t }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [resetNewPassword, setResetNewPassword] = useState('')
  const [resetRequestSent, setResetRequestSent] = useState(false)
  const [resetDone, setResetDone] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setError('')
    setPassword('')
    setResetRequestSent(false)
    setResetDone(false)
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

  async function handleResetRequest(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await authRequest('/api/auth/password/reset/request', {
        method: 'POST',
        body: JSON.stringify({ email }),
      })
      setResetRequestSent(true)
    } catch (requestError) {
      setError(requestError.message || t.auth.genericError)
    } finally {
      setLoading(false)
    }
  }

  async function handleResetConfirm(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await authRequest('/api/auth/password/reset/confirm', {
        method: 'POST',
        body: JSON.stringify({ token: resetToken, new_password: resetNewPassword }),
      })
      setResetDone(true)
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
          <AccountView identity={identity} onIdentityChange={onIdentityChange} onClose={onClose} t={t} />
        ) : mode === 'reset-request' ? (
          <>
            <span className="auth-kicker">{t.auth.anonymousFirst}</span>
            <h2 id="auth-title">{t.auth.resetRequestTitle}</h2>
            {!resetRequestSent ? (
              <form className="auth-form" onSubmit={handleResetRequest}>
                <p className="auth-description">{t.auth.resetRequestDescription}</p>
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
                {error && <p className="auth-error" role="alert">{error}</p>}
                <button className="auth-submit" type="submit" disabled={loading}>
                  {loading ? t.auth.working : t.auth.resetRequestSubmit}
                </button>
              </form>
            ) : !resetDone ? (
              <form className="auth-form" onSubmit={handleResetConfirm}>
                <p className="auth-hint">{t.auth.resetRequestSent}</p>
                <label>
                  <span>{t.auth.resetTokenLabel}</span>
                  <input value={resetToken} onChange={event => setResetToken(event.target.value)} required />
                </label>
                <label>
                  <span>{t.auth.resetNewPasswordLabel}</span>
                  <input
                    type="password"
                    value={resetNewPassword}
                    onChange={event => setResetNewPassword(event.target.value)}
                    autoComplete="new-password"
                    minLength={10}
                    maxLength={128}
                    required
                  />
                </label>
                {error && <p className="auth-error" role="alert">{error}</p>}
                <button className="auth-submit" type="submit" disabled={loading}>
                  {loading ? t.auth.working : t.auth.resetConfirmSubmit}
                </button>
              </form>
            ) : (
              <p className="auth-hint">{t.auth.resetSuccess}</p>
            )}
            <button className="auth-link-button" type="button" onClick={() => setMode('login')}>
              {t.auth.backToLogin}
            </button>
          </>
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
            {mode === 'login' && (
              <button className="auth-link-button" type="button" onClick={() => setMode('reset-request')}>
                {t.auth.forgotPassword}
              </button>
            )}
          </>
        )}
      </section>
    </div>
  )
}
