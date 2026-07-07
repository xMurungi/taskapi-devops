// packages/app/src/App.tsx
import './style.css';
import React from 'react';
import { createApp } from '@backstage/frontend-defaults';
import { UnifiedThemeProvider } from '@backstage/theme';
import { ncbaDarkTheme } from './theme';
import { Grid } from '@material-ui/core';

// Core entity types and built-in condition blocks
import { Entity } from '@backstage/catalog-model';
import {
  EntitySwitch,
  EntityAboutCard,
  EntityDependsOnComponentsCard,
  EntityDependsOnResourcesCard,
} from '@backstage/plugin-catalog';

// Safe Alpha layouts and plugin hooks
import catalogPlugin from '@backstage/plugin-catalog/alpha';
import apiDocsPlugin from '@backstage/plugin-api-docs/alpha';
import { navModule } from './modules/nav';

// Safe UI component imports
import { EntityProvidedApisCard, EntityConsumedApisCard } from '@backstage/plugin-api-docs';

// Strictly typed helper utilities to check runtime relations
const hasProvidedApis = (entity: Entity): boolean => 
  entity?.relations?.some((r: { type: string }) => r.type === 'providesApi') ?? false;

const hasConsumedApis = (entity: Entity): boolean => 
  entity?.relations?.some((r: { type: string }) => r.type === 'consumesApi') ?? false;

const hasDependencies = (entity: Entity): boolean => 
  entity?.relations?.some((r: { type: string }) => r.type === 'dependsOn') ?? false;

export default createApp({
  features: [
    apiDocsPlugin, 
    navModule,
    
    // Inject the conditional view blocks as an extension override to the catalog plugin
    catalogPlugin.withOverrides({
      extensions: [
        catalogPlugin.getExtension('page:catalog/entity').override({
          loader: async () => {
            return () => (
              <Grid container spacing={3} alignItems="stretch">
                <Grid item md={8} xs={12}>
                  
                  {/* 1. Only show Provided APIs if they actually exist */}
                  <EntitySwitch>
                    <EntitySwitch.Case if={hasProvidedApis}>
                      <Grid item xs={12}>
                        <EntityProvidedApisCard />
                      </Grid>
                    </EntitySwitch.Case>
                  </EntitySwitch>

                  {/* 2. Only show Consumed APIs if they actually exist */}
                  <EntitySwitch>
                    <EntitySwitch.Case if={hasConsumedApis}>
                      <Grid item xs={12}>
                        <EntityConsumedApisCard />
                      </Grid>
                    </EntitySwitch.Case>
                  </EntitySwitch>

                  {/* 3. Only show Component Dependencies if they actually exist */}
                  <EntitySwitch>
                    <EntitySwitch.Case if={hasDependencies}>
                      <Grid item xs={12}>
                        <EntityDependsOnComponentsCard />
                      </Grid>
                    </EntitySwitch.Case>
                  </EntitySwitch>

                  {/* 4. Keeps your resources / RabbitMQ queues visible */}
                  <Grid item xs={12}>
                    <EntityDependsOnResourcesCard />
                  </Grid>
                </Grid>

                {/* Right side tracking metadata */}
                <Grid item md={4} xs={12}>
                  <EntityAboutCard />
                </Grid>
              </Grid>
            );
          },
        }),
      ],
    }),
  ],
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