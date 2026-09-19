import '@fontsource-variable/bricolage-grotesque/wdth.css';
import '@fontsource-variable/martian-mono/wght.css';
import './styles/tokens.css';
import './styles/shell.css';
import './styles/cockpit.css';
import './styles/pages.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
