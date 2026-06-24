import { useConnection } from "./state/connection";

export default function App() {
  const connection = useConnection();

  return <div role="status">Connection: {connection.state}</div>;
}
