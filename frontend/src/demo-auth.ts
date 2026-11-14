import type {ViewRole} from './types';

export type DemoIdentity = Readonly<{username: string; role: ViewRole}>;
// Deliberately public test credentials. This is an offline UI simulation,
// not a security boundary. Real authorization belongs to the FastAPI backend.
const accounts = [
  {username:'demo.user',password:'ReviewDemo!26',role:'user'},
  {username:'demo.lawyer',password:'LegalDemo!26',role:'lawyer'},
] as const;

export function authenticateDemo(username: string,password: string,requestedRole: ViewRole): DemoIdentity {
  const account=accounts.find(a=>a.username===username.trim().toLowerCase()&&a.password===password);
  if(!account)throw new Error('Incorrect username or password. Use your demo account.');
  if(account.role!==requestedRole)throw new Error(`This account belongs to the ${account.role==='lawyer'?'Lawyer':'User'} workspace. Select that role to sign in.`);
  return Object.freeze({username:account.username,role:account.role});
}

// Test convenience only: these are public demo fixtures, never saved real credentials.
export function demoCredentials(role: ViewRole) {
  const account=accounts.find(a=>a.role===role)!;
  return {username:account.username,password:account.password};
}
