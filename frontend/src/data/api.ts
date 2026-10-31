import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api, serverMode } from "@/lib/server";
import { registerDescriptions } from "./clinical";
import type { Catalog, EcgDetail, HolterDetail } from "./types";

const BASE = `${import.meta.env.BASE_URL}data`;

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}/${path}`);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

/** Recording times are stored relative to the build date; shift them so the newest ECG is always "today". */
function shiftTimes(c: Catalog): Catalog {
  const offset = Date.now() - new Date(c.generated).getTime();
  const shift = (iso: string) => new Date(new Date(iso).getTime() + offset).toISOString();
  return {
    ...c,
    ecgs: c.ecgs.map((e) => ({ ...e, recorded_at: shift(e.recorded_at) })),
    holters: c.holters.map((h) => ({ ...h, recorded_at: shift(h.recorded_at) })),
  };
}

export function useCatalog() {
  return useQuery({
    queryKey: ["catalog"],
    staleTime: Infinity,
    queryFn: async () => {
      const c = serverMode ? await api<Catalog>("/catalog") : shiftTimes(await getJson<Catalog>("catalog.json"));
      registerDescriptions(c.statement_descriptions);
      return c;
    },
  });
}

export function useEcg(id: string | undefined) {
  return useQuery({ queryKey: ["ecg", id], queryFn: () => (serverMode ? api<EcgDetail>(`/ecg/${id}`) : getJson<EcgDetail>(`ecg/${id}.json`)), enabled: !!id, staleTime: Infinity });
}

/** Recordings longer than this load the signal in blocks around what is on screen (a 24 h Holter is ~40 MB). */
export const HOLTER_FULL_LOAD_S = 2 * 3600;
const BLOCK_S = 300;

/** The signal around [start, start + seconds) as { signal, offset } (offset = sample index of signal[0]). */
export function useHolterWindow(id: string | undefined, fs: number, start: number, seconds: number, enabled: boolean) {
  const first = Math.floor(Math.max(0, start) / BLOCK_S), last = Math.floor((start + seconds) / BLOCK_S);
  const blocks = useQueries({
    queries: Array.from({ length: last - first + 1 }, (_, k) => first + k).map((b) => ({
      queryKey: ["holter-block", id, b],
      enabled: enabled && !!id,
      staleTime: Infinity,
      queryFn: () => api<ArrayBuffer>(`/holter/${id}/signal?from=${b * BLOCK_S}&to=${(b + 1) * BLOCK_S}`).then((buf) => int16ToMv(new Int16Array(buf))),
    })),
  });
  return useMemo(() => {
    if (!enabled || blocks.some((b) => !b.data)) return null;
    const parts = blocks.map((b) => b.data!);
    const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
    let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return { signal: out, offset: Math.round(first * BLOCK_S * fs) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, first, fs, ...blocks.map((b) => b.data)]);
}

export function useHolter(id: string | undefined) {
  return useQuery({
    queryKey: ["holter", id],
    enabled: !!id,
    staleTime: Infinity,
    queryFn: async () => {
      if (serverMode) {
        const detail = await api<HolterDetail>(`/holter/${id}`);
        const long = detail.n_samples / detail.fs > HOLTER_FULL_LOAD_S;
        const signal = long ? null : int16ToMv(new Int16Array(await api<ArrayBuffer>(`/holter/${id}/signal`)));
        return { detail, signal };
      }
      const [detail, buf] = await Promise.all([
        getJson<HolterDetail>(`holter/${id}.json`),
        fetch(`${BASE}/holter/${id}.i16`).then((r) => {
          if (!r.ok) throw new Error(`holter signal: HTTP ${r.status}`);
          return r.arrayBuffer();
        }),
      ]);
      return { detail, signal: int16ToMv(new Int16Array(buf)) as Float32Array | null };
    },
  });
}

/** int16 µV → Float32 mV */
export function int16ToMv(a: Int16Array): Float32Array {
  const out = new Float32Array(a.length);
  for (let i = 0; i < a.length; i++) out[i] = a[i] / 1000;
  return out;
}

export function decodeLead(b64: string): Float32Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return int16ToMv(new Int16Array(bytes.buffer));
}


/** Decoded waveforms of one ECG: full 10 s leads and the median beat per lead. */
export function useEcgSignals(id: string | undefined) {
  const q = useEcg(id);
  const signals = useMemo(() => {
    if (!q.data) return null;
    const leads: Record<string, Float32Array> = {};
    for (const [k, v] of Object.entries(q.data.leads)) leads[k] = decodeLead(v);
    const median: Record<string, Float32Array> = {};
    if (q.data.median) for (const [k, v] of Object.entries(q.data.median.leads)) median[k] = decodeLead(v);
    return { leads, median };
  }, [q.data]);
  return { ...q, signals };
}
