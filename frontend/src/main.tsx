import {StrictMode, Component, type ReactNode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App';
import './styles.css';
class Boundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  render(){return this.state.failed?<main className="fatal"><h1>Something interrupted this view.</h1><p>Reload to return to role selection. Your live session will be cleared.</p><button onClick={()=>location.reload()}>Reload Greenlight</button></main>:this.props.children;}
}
createRoot(document.getElementById('root')!).render(<StrictMode><Boundary><App/></Boundary></StrictMode>);
