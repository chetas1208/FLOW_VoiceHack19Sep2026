import type { ThreeElements } from '@react-three/fiber';

// @react-three/fiber v8 augments the removed global JSX namespace; @types/react 19
// moved JSX into the react module, so re-target the augmentation there.
declare module 'react' {
  namespace JSX {
    interface IntrinsicElements extends ThreeElements {}
  }
}
