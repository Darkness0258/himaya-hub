import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { useHub } from './store'
import type { Snapshot } from './types'

/** Screenshots for one device (or all), refreshed when a new screenshot event arrives. */
export function useSnapshots(deviceId?: string, pageSize = 24) {
  const { events } = useHub()
  const [items, setItems] = useState<Snapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [hasMore, setHasMore] = useState(false)

  const shotCount = useMemo(() => events.filter((e) => e.type === 'screenshot' && (!deviceId || e.device_id === deviceId)).length, [events, deviceId])

  const load = useCallback(async () => {
    try {
      const rows = await api.snapshots({ device_id: deviceId, limit: pageSize })
      setItems(rows)
      setHasMore(rows.length === pageSize)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load screenshots.')
    } finally {
      setLoading(false)
    }
  }, [deviceId, pageSize])

  useEffect(() => {
    setLoading(true)
    void load()
  }, [load])
  useEffect(() => {
    if (shotCount > 0) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shotCount])

  const loadMore = useCallback(async () => {
    const last = items[items.length - 1]
    if (!last) return
    const rows = await api.snapshots({ device_id: deviceId, limit: pageSize, before_id: last.id })
    setItems((current) => [...current, ...rows])
    setHasMore(rows.length === pageSize)
  }, [items, deviceId, pageSize])

  const remove = useCallback(async (id: number) => {
    await api.deleteSnapshot(id)
    setItems((current) => current.filter((item) => item.id !== id))
  }, [])

  return { items, loading, error, hasMore, loadMore, remove, refetch: load }
}
