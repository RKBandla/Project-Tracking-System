import { useState } from 'react';
import { assignmentsApi } from '../api/services';
import { Pagination } from '../components/DataTable';
import { EmptyState, ErrorState, Loading } from '../components/Feedback';
import { Card, FilterBar, PageHeader } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { addDays, formatShortDate, mondayOf, today } from '../utils/format';

const PAGE_SIZE = 50;

/** Allocation grid: people down, weeks across; cells at 40 hours (or over) are flagged. */
export default function AllocationPage() {
  const [from, setFrom] = useState(mondayOf(today()));
  const [weeks, setWeeks] = useState(12);
  const [search, setSearch] = useState('');
  const [onlyBooked, setOnlyBooked] = useState(false);
  const [page, setPage] = useState(1);
  const q = useDebouncedValue(search);

  const query = { from, weeks, q, only_over: onlyBooked ? 'true' : '', page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useAsync(() => assignmentsApi.grid(query), JSON.stringify(query));

  const shift = (delta) => { setFrom((f) => addDays(f, delta * 7)); };

  return (
    <>
      <PageHeader
        title="Allocation"
        subtitle="Hours booked per person per week. Nobody can go over 40 hours in a week."
        actions={(
          <div className="segmented" role="group" aria-label="Move weeks">
            <button type="button" onClick={() => shift(-4)} aria-label="Previous 4 weeks">‹</button>
            <button type="button" onClick={() => setFrom(mondayOf(today()))}>This week</button>
            <button type="button" onClick={() => shift(4)} aria-label="Next 4 weeks">›</button>
          </div>
        )}
      />
      <FilterBar>
        <input type="search" className="search-input" placeholder="Search people…" aria-label="Search people"
          value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
        <select aria-label="Number of weeks" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
          {[4, 8, 12, 26].map((n) => <option key={n} value={n}>{n} weeks</option>)}
        </select>
        <label className="inline-check">
          <input type="checkbox" checked={onlyBooked} onChange={(e) => { setOnlyBooked(e.target.checked); setPage(1); }} />
          Only people with bookings
        </label>
      </FilterBar>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <Card className={loading ? 'is-refreshing' : undefined}>
          <div className="grid-legend muted">
            <span><i className="cell-swatch level-1" /> 1–19 h</span>
            <span><i className="cell-swatch level-2" /> 20–39 h</span>
            <span><i className="cell-swatch full" /> 40 h (full)</span>
            <span><i className="cell-swatch over" /> over 40 h</span>
            {data.over_allocated_people > 0 && (
              <strong className="text-danger">{data.over_allocated_people} over-allocated</strong>
            )}
          </div>
          {data.rows.length === 0 ? <EmptyState title="Nobody matches" /> : (
            <div className="alloc-scroll" tabIndex={0} aria-label="Allocation grid, scrolls sideways">
              <table className="alloc-grid">
                <caption className="sr-only">Booked hours per person per week</caption>
                <thead>
                  <tr>
                    <th scope="col" className="alloc-person">Person</th>
                    {data.weeks.map((w) => <th key={w} scope="col">{formatShortDate(w)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.id}>
                      <th scope="row" className="alloc-person">
                        <strong>{row.full_name}</strong>
                        <span className="muted">{row.job_title}</span>
                      </th>
                      {row.cells.map((c) => {
                        const level = c.over ? 'over' : c.full ? 'full' : c.hours >= 20 ? 'level-2' : c.hours > 0 ? 'level-1' : '';
                        const detail = c.projects.map((p) => `${p.code ? `${p.code} ` : ''}${p.name}: ${p.hours} h`).join('\n');
                        return (
                          <td key={c.week_start} className={`alloc-cell ${level}`} title={detail || 'Not booked'}>
                            {c.hours ? `${c.hours}` : ''}
                            {c.over && <span className="sr-only"> hours, over the limit</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </Card>
      )}
    </>
  );
}
