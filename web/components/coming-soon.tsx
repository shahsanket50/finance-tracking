interface Props {
  phase: string;
  screen: string;
}

export function ComingSoon({ phase, screen }: Props) {
  return (
    <div className="screen">
      <div className="page-head">
        <h2>{screen}</h2>
        <p>Coming in Phase {phase}</p>
      </div>
    </div>
  );
}
