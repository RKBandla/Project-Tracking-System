/**
 * Diamond marker for a milestone (a checkpoint with a single date).
 *
 * @param {{title?: string}} props
 */
export default function MilestoneMark({ title = 'Milestone' }) {
  return <span className="milestone-mark" role="img" aria-label={title} title={title}>◆</span>;
}
