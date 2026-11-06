import { es } from "../i18n/es";

export function Timeline() {
  return (
    <footer className="shell-timeline" data-testid="timeline">
      <p className="empty">{es.timeline.empty}</p>
    </footer>
  );
}
