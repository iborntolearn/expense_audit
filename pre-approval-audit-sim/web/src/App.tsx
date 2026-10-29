import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './lib/auth'
import { ToastProvider } from './lib/toast'
import { AppShell } from './components/layout/AppShell'
import { ProtectedRoute } from './components/layout/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { ExpenseReportsPage } from './pages/ExpenseReportsPage'
import { UserAnalyticsPage } from './pages/UserAnalyticsPage'
import { AssistantPage } from './pages/AssistantPage'
import { ReportsExportsPage } from './pages/ReportsExportsPage'
import { SettingsPage } from './pages/SettingsPage'
import { SystemAdminPage } from './pages/SystemAdminPage'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false } },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <ProtectedRoute>
                    <AppShell />
                  </ProtectedRoute>
                }
              >
                <Route path="/" element={<DashboardPage />} />
                <Route path="/expenses" element={<ExpenseReportsPage />} />
                <Route
                  path="/analytics"
                  element={
                    <ProtectedRoute roles={['admin', 'user']}>
                      <UserAnalyticsPage />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/assistant"
                  element={
                    <ProtectedRoute roles={['admin', 'user']}>
                      <AssistantPage />
                    </ProtectedRoute>
                  }
                />
                <Route path="/reports" element={<ReportsExportsPage />} />
                <Route
                  path="/settings"
                  element={
                    <ProtectedRoute roles={['admin']}>
                      <SettingsPage />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/system-admin"
                  element={
                    <ProtectedRoute roles={['admin']}>
                      <SystemAdminPage />
                    </ProtectedRoute>
                  }
                />
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  )
}

export default App
