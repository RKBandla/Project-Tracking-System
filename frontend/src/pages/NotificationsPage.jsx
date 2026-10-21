import { useState } from 'react';
import { activityApi } from '../api/services';
import { Pagination } from '../components/DataTable';
import { EmptyState, ErrorState, Loading } from '../components/Feedback';
import { Card, FilterBar, PageHeader } from '../components/PageParts';
import { useAsync } from '../hooks/useAsync';
import { Link } from '../router/Router';
import { label, timeAgo } from '../utils/format';

const PAGE_SIZE = 30;

/** Where a notification about an entity should link to. */
function linkFor(n) {
  if (n.entity === 'project') return `/projects/${n.entity_id}`;
  if (n.entity === 'project_request') return '/requests';
  if (n.entity === 'time_entry') return '/approvals';
  if (n.entity === 'user') return '/users';
  return null;
}

/** In-app notifications: changes made by people who report to you (directly or further down). */
export default function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const query = { unread: unreadOnly ? 'true' : '', page, page_size: PAGE_SIZE };
  const { data, error, loading, reload } = useAsync(() => activityApi.notifications(query), JSON.stringify(query));

  const markAll = async () => { await activityApi.markAllRead(); reload(); };
  const open = async (n) => { if (!n.read_at) { await activityApi.markRead(n.id); reload(); } };

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Every change made by someone in your reporting line."
        actions={data?.unread > 0 && <button type="button" className="btn btn-secondary" onClick={markAll}>Mark all as read</button>}
      />
      <FilterBar>
        <label className="inline-check">
          <input type="checkbox" checked={unreadOnly} onChange={(e) => { setUnreadOnly(e.target.checked); setPage(1); }} />
          Unread only
        </label>
      </FilterBar>
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <Card>
          {data.items.length === 0 ? <EmptyState title={unreadOnly ? 'No unread notifications' : 'No notifications yet'} /> : (
            <ul className="notification-list">
              {data.items.map((n) => {
                const to = linkFor(n);
                const body = (
                  <>
                    <span className="notification-text">{n.message}</span>
                    <span className="muted">{label(n.entity)} · {timeAgo(n.created_at)}</span>
                  </>
                );
                return (
                  <li key={n.id} className={n.read_at ? 'read' : 'unread'}>
                    {!n.read_at && <span className="unread-dot" aria-label="Unread" />}
                    {to ? <Link to={to} className="notification-body" onClick={() => open(n)}>{body}</Link>
                      : <button type="button" className="notification-body" onClick={() => open(n)}>{body}</button>}
                  </li>
                );
              })}
            </ul>
          )}
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </Card>
      )}
    </>
  );
}
