export type RenderPresetValue =
  | 'low'
  | 'medium'
  | 'high'
  | 'low_av1'
  | 'medium_av1'
  | 'high_av1';

interface RenderPresetOption {
  value: RenderPresetValue;
  label: string;
  description?: string;
}

export const renderPresets: RenderPresetOption[] = [
  {
    value: 'low',
    label: 'Low h265',
    description: 'Rapide, qualité basse',
  },
  {
    value: 'medium',
    label: 'Medium h265',
    description: 'Compromis qualité / taille',
  },
  {
    value: 'high',
    label: 'High h265',
    description: 'Meilleure qualité classique',
  },
  {
    value: 'low_av1',
    label: 'Low AV1',
    description: 'AV1 CPU, petit fichier',
  },
  {
    value: 'medium_av1',
    label: 'Medium AV1',
    description: 'AV1 CPU, compromis',
  },
  {
    value: 'high_av1',
    label: 'High AV1',
    description: 'AV1 CPU, qualité élevée',
  },
];
