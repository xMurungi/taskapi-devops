import './style.css';
import React from 'react';
import { createApp } from '@backstage/frontend-defaults';
import catalogPlugin from '@backstage/plugin-catalog/alpha';
import { navModule } from './modules/nav';
import { UnifiedThemeProvider } from '@backstage/theme';
import { ncbaDarkTheme } from './theme';

export default createApp({
  features: [catalogPlugin, navModule],
  themes: [
    {
      id: 'ncba-dark',
      title: 'NCBA Dark',
      variant: 'dark',
      Provider: ({ children }: { children?: React.ReactNode }) => (
        <UnifiedThemeProvider theme={ncbaDarkTheme} children={children} />
      ),
    },
  ],
} as any);