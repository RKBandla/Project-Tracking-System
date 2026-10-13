/**
 * Responsive data table. On narrow screens CSS turns each row into a card,
 * using each cell's data-label as its caption.
 *
 * @param {{
 *   columns: {key: string, label: string, render?: Function, sortKey?: string, className?: string}[],
 *   rows: object[],
 *   sort?: string,
 *   onSort?: Function,
 *   onRowClick?: Function,
 *   rowLabel?: Function,
 *   empty?: React.ReactNode,
 *   caption?: string,
 * }} props
 */
export function DataTable({ columns, rows, sort, onSort, onRowClick, rowLabel, empty, caption }) {
  if (!rows.length) {
    return <div className="table-empty">{empty || 'Nothing to show.'}</div>;
  }
  const activeKey = sort?.replace(/^-/, '');
  const descending = sort?.startsWith('-');

  const header = (col) => {
    if (!col.sortKey || !onSort) return col.label;
    const active = activeKey === col.sortKey;
    const next = active && !descending ? `-${col.sortKey}` : col.sortKey;
    return (
      <button type="button" className={`sort-btn ${active ? 'active' : ''}`} onClick={() => onSort(next)}>
        {col.label}
        <span aria-hidden="true">{active ? (descending ? ' ↓' : ' ↑') : ''}</span>
      </button>
    );
  };

  return (
    <div className="table-wrap">
      <table className="data-table">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={col.className}
                aria-sort={activeKey && activeKey === col.sortKey ? (descending ? 'descending' : 'ascending') : undefined}
              >
                {header(col)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={onRowClick ? 'clickable' : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={onRowClick ? (e) => { if (e.key === 'Enter') onRowClick(row); } : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              aria-label={onRowClick && rowLabel ? rowLabel(row) : undefined}
            >
              {columns.map((col) => (
                <td key={col.key} data-label={col.label} className={col.className}>
                  {col.render ? col.render(row) : row[col.key] ?? '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Previous/next pagination with a result count.
 *
 * @param {{page: number, pageSize: number, total: number, onChange: Function}} props
 */
export function Pagination({ page, pageSize, total, onChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="muted">{from}–{to} of {total}</span>
      <div className="pagination-buttons">
        <button type="button" className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          Previous
        </button>
        <span className="muted">Page {page} of {pages}</span>
        <button type="button" className="btn btn-ghost btn-sm" disabled={page >= pages} onClick={() => onChange(page + 1)}>
          Next
        </button>
      </div>
    </nav>
  );
}
