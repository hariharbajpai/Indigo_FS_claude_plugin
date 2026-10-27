import { Routes, Route, Navigate } from 'react-router-dom'
import { LiveProvider } from './useLive.js'
import Layout from './components/Layout.jsx'
import Overview from './views/Overview.jsx'
import TaskBoard from './views/TaskBoard.jsx'
import OrgChart from './views/OrgChart.jsx'
import ChatFeed from './views/ChatFeed.jsx'
import OwnerConsole from './views/OwnerConsole.jsx'

export default function App() {
  return (
    <LiveProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="board" element={<TaskBoard />} />
          <Route path="org" element={<OrgChart />} />
          <Route path="chat" element={<ChatFeed />} />
          <Route path="console" element={<OwnerConsole />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </LiveProvider>
  )
}
