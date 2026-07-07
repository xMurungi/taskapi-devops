import {
  createBaseThemeOptions,
  createUnifiedTheme,
  genPageTheme,
  palettes,
  shapes,
} from '@backstage/theme';

export const ncbaDarkTheme = createUnifiedTheme({
  ...createBaseThemeOptions({
    palette: {
      ...palettes.dark,
      primary: { main: '#3fb950' },
      background: { default: '#0a0c10', paper: '#161b22' },
      navigation: {
        background: '#111318',
        indicator: '#3fb950',
        color: '#006fef',
        selectedColor: '#0084f8',
      },
    },
  }),
  fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
  defaultPageTheme: 'home',
  components: {
  BackstageSidebar: {
    styleOverrides: {
      drawer: {
        backgroundColor: '#111318',
      },
    },
  },
  BackstageSidebarItem: {
    styleOverrides: {
      root: {
        color: '#006fef',
      },
      label: {
        color: '#006fef',
        '&:hover': {
          color: '#0084f8',
        },
      },
      selected: {
        color: '#0084f8 !important',
        '& $label': {
          color: '#0084f8 !important',
        },
      },
    },
  },
  BackstageSidebarDivider: {
    styleOverrides: {
      root: {
        backgroundColor: 'rgba(0, 111, 239, 0.15)',
      },
    },
  },
  MuiCssBaseline: {
    styleOverrides: {
      body: {
        backgroundColor: '#0a0c10',
        color: '#e6edf3',
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
      },
      // Scrollbar
      '*::-webkit-scrollbar': {
        width: '6px',
        height: '6px',
      },
      '*::-webkit-scrollbar-track': {
        background: '#0a0c10',
      },
      '*::-webkit-scrollbar-thumb': {
        background: '#21262d',
        borderRadius: '3px',
      },
    },
  },
  MuiPaper: {
    styleOverrides: {
      root: {
        backgroundColor: '#161b22',
        backgroundImage: 'none',
        borderRadius: '8px',
        border: '1px solid #21262d',
      },
    },
  },
  MuiCard: {
    styleOverrides: {
      root: {
        backgroundColor: '#161b22',
        backgroundImage: 'none',
        border: '1px solid #21262d',
        borderRadius: '8px',
      },
    },
  },
  MuiCardHeader: {
    styleOverrides: {
      root: {
        borderBottom: '1px solid #21262d',
        padding: '16px 20px',
      },
      title: {
        fontSize: '14px',
        fontWeight: 700,
        color: '#e6edf3',
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
      },
      subheader: {
        color: '#8b949e',
        fontSize: '12px',
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
      },
    },
  },
  MuiCardContent: {
    styleOverrides: {
      root: {
        padding: '16px 20px',
        '&:last-child': {
          paddingBottom: '16px',
        },
      },
    },
  },
  MuiTableContainer: {
    styleOverrides: {
      root: {
        backgroundColor: '#161b22',
        border: '1px solid #21262d',
        borderRadius: '8px',
      },
    },
  },
  MuiTableHead: {
    styleOverrides: {
      root: {
        backgroundColor: '#111318',
        '& .MuiTableCell-root': {
          color: '#8b949e',
          fontSize: '11px',
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          borderBottom: '1px solid #21262d',
          fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        },
      },
    },
  },
  MuiTableRow: {
    styleOverrides: {
      root: {
        '&:hover': {
          backgroundColor: '#1c2128 !important',
        },
        '&:last-child td': {
          borderBottom: 'none',
        },
      },
    },
  },
  MuiTableCell: {
    styleOverrides: {
      root: {
        borderBottom: '1px solid #21262d',
        color: '#e6edf3',
        fontSize: '13px',
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        padding: '12px 16px',
      },
    },
  },
  MuiTab: {
    styleOverrides: {
      root: {
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        fontSize: '12px',
        fontWeight: 600,
        letterSpacing: '0.05em',
        textTransform: 'uppercase',
        color: '#8b949e',
        '&.Mui-selected': {
          color: '#3fb950',
        },
        minWidth: 'unset',
        padding: '10px 16px',
      },
    },
  },
  MuiTabs: {
    styleOverrides: {
      indicator: {
        backgroundColor: '#3fb950',
        height: '2px',
      },
      root: {
        borderBottom: '1px solid #21262d',
      },
    },
  },
  MuiButton: {
    styleOverrides: {
      root: {
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        fontSize: '12px',
        fontWeight: 700,
        letterSpacing: '0.05em',
        textTransform: 'uppercase',
        borderRadius: '6px',
      },
      containedPrimary: {
        backgroundColor: '#238636',
        color: '#fff',
        '&:hover': {
          backgroundColor: '#3fb950',
        },
      },
      outlinedPrimary: {
        borderColor: '#238636',
        color: '#3fb950',
        '&:hover': {
          borderColor: '#3fb950',
          backgroundColor: 'rgba(63, 185, 80, 0.08)',
        },
      },
    },
  },
  MuiChip: {
    styleOverrides: {
      root: {
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        fontSize: '11px',
        backgroundColor: '#21262d',
        color: '#8b949e',
        border: '1px solid #30363d',
        borderRadius: '4px',
      },
      colorPrimary: {
        backgroundColor: 'rgba(63, 185, 80, 0.15)',
        color: '#3fb950',
        border: '1px solid rgba(63, 185, 80, 0.3)',
      },
    },
  },
  MuiInputBase: {
    styleOverrides: {
      root: {
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        fontSize: '13px',
        backgroundColor: '#0a0c10',
        border: '1px solid #21262d',
        borderRadius: '6px',
        color: '#e6edf3',
        '&:hover': {
          borderColor: '#30363d',
        },
        '&.Mui-focused': {
          borderColor: '#3fb950',
          boxShadow: '0 0 0 3px rgba(63, 185, 80, 0.1)',
        },
      },
    },
  },
  MuiOutlinedInput: {
    styleOverrides: {
      notchedOutline: {
        borderColor: '#21262d',
      },
      root: {
        '&:hover .MuiOutlinedInput-notchedOutline': {
          borderColor: '#30363d',
        },
        '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
          borderColor: '#3fb950',
        },
      },
    },
  },
  MuiListItem: {
    styleOverrides: {
      root: {
        '&.Mui-selected': {
          backgroundColor: 'rgba(63, 185, 80, 0.08)',
          '&:hover': {
            backgroundColor: 'rgba(63, 185, 80, 0.12)',
          },
        },
        '&:hover': {
          backgroundColor: '#1c2128',
        },
      },
    },
  },
  MuiDivider: {
    styleOverrides: {
      root: {
        borderColor: '#21262d',
      },
    },
  },
  MuiTypography: {
    styleOverrides: {
      root: {
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
      },
      h1: { color: '#e6edf3' },
      h2: { color: '#e6edf3' },
      h3: { color: '#e6edf3' },
      h4: { color: '#e6edf3' },
      h5: { color: '#e6edf3' },
      h6: { color: '#e6edf3' },
      subtitle1: { color: '#8b949e' },
      subtitle2: { color: '#8b949e' },
      body1: { color: '#e6edf3' },
      body2: { color: '#8b949e' },
    },
  },
  MuiSwitch: {
    styleOverrides: {
      switchBase: {
        '&.Mui-checked': {
          color: '#3fb950',
          '& + .MuiSwitch-track': {
            backgroundColor: '#238636',
          },
        },
      },
    },
  },
  MuiTooltip: {
    styleOverrides: {
      tooltip: {
        backgroundColor: '#161b22',
        border: '1px solid #21262d',
        color: '#e6edf3',
        fontSize: '11px',
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        borderRadius: '6px',
      },
    },
  },
  MuiAlert: {
    styleOverrides: {
      root: {
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        fontSize: '12px',
        borderRadius: '6px',
      },
      standardInfo: {
        backgroundColor: 'rgba(88, 166, 255, 0.1)',
        border: '1px solid rgba(88, 166, 255, 0.3)',
        color: '#58a6ff',
      },
      standardSuccess: {
        backgroundColor: 'rgba(63, 185, 80, 0.1)',
        border: '1px solid rgba(63, 185, 80, 0.3)',
        color: '#3fb950',
      },
      standardWarning: {
        backgroundColor: 'rgba(227, 179, 65, 0.1)',
        border: '1px solid rgba(227, 179, 65, 0.3)',
        color: '#e3b341',
      },
      standardError: {
        backgroundColor: 'rgba(248, 81, 73, 0.1)',
        border: '1px solid rgba(248, 81, 73, 0.3)',
        color: '#f85149',
      },
    },
  },
},
});