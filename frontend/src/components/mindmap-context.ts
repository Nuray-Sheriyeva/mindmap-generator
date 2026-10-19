import { createContext } from 'react';

export interface MindMapActions {
  toggleNode: (id: string) => void;
}

export const MindMapActionsContext = createContext<MindMapActions | null>(null);
