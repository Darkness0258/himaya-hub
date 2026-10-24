import '@fontsource-variable/fraunces/index.css'
import '@fontsource-variable/figtree/index.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/app.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
