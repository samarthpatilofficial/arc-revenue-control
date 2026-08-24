import { useCallback, useEffect, useState } from "react";

interface ApiResource<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  retry: () => void;
}

export function useApiResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
): ApiResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [requestVersion, setRequestVersion] = useState(0);
  const retry = useCallback(() => setRequestVersion((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setLoading(true);
      setError(null);
      loader(controller.signal)
        .then((value) => {
          if (!controller.signal.aborted) {
            setData(value);
            setLoading(false);
          }
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setError(reason instanceof Error ? reason : new Error("Request failed"));
            setLoading(false);
          }
        });
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [loader, requestVersion]);

  return { data, error, loading, retry };
}
