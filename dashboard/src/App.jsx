import { Redirect, Route, Switch } from 'wouter';
import { Loader2 } from 'lucide-react';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/useAuth';
import AuthScreen from './screens/AuthScreen';
import Layout from './components/Layout';
import SecretsScreen from './screens/SecretsScreen';
import CapabilityDetailScreen from './screens/CapabilityDetailScreen';
import AiBuilderScreen from './screens/AiBuilderScreen';
import { ActivityScreen, AutomationsScreen, CommandCenterScreen, RequestsScreen, SecurityScreen, ServicesScreen, SettingsScreen, ToolsScreen, VerificationScreen } from './screens/ControlPlaneScreens';

function Gate() {
  const { authed, checking } = useAuth();

  if (checking) {
    return <div className="flex min-h-svh items-center justify-center bg-background"><Loader2 size={20} className="animate-spin text-muted" /></div>;
  }
  if (!authed) return <AuthScreen />;

  return (
    <Layout>
      <Switch>
        <Route path="/"><Redirect to="/command-center" replace /></Route>
        <Route path="/command-center" component={CommandCenterScreen} />
        <Route path="/activity" component={ActivityScreen} />
        <Route path="/ai-builder" component={AiBuilderScreen} />
        <Route path="/services" component={ServicesScreen} />
        <Route path="/tools/:id">{() => <CapabilityDetailScreen kind="tool" />}</Route>
        <Route path="/tools" component={ToolsScreen} />
        <Route path="/automations/:id">{() => <CapabilityDetailScreen kind="automation" />}</Route>
        <Route path="/automations" component={AutomationsScreen} />
        <Route path="/requests" component={RequestsScreen} />
        <Route path="/verification" component={VerificationScreen} />
        <Route path="/security" component={SecurityScreen} />
        <Route path="/settings" component={SettingsScreen} />
        <Route path="/secrets" component={SecretsScreen} />
        <Route><Redirect to="/command-center" replace /></Route>
      </Switch>
    </Layout>
  );
}

export default function App() {
  return <AuthProvider><Gate /></AuthProvider>;
}
