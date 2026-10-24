export function canonical(value: unknown): string;
export function fields(value: unknown, allowed: readonly string[]): void;
export function sha256Hex(message: string): string;
export function validateVerification<T>(input: { people: { id: string }[]; actions: { actionId: string; revisionId: string }[]; assessments: { id: string }[] }, receipt: T, inputHash: string, hash: (value: string) => string): T;
