import { es } from "../i18n/es";

export function Inspector() {
  return (
    <aside className="shell-inspector" data-testid="inspector">
      <p className="empty">{es.inspector.empty}</p>
    </aside>
  );
}
