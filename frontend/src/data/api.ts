import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
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
      const c = shiftTimes(await getJson<Catalog>("catalog.json"));
      registerDescriptions(c.statement_descriptions);
      return c;
    },
  });
}

export function useEcg(id: string | undefined) {
  return useQuery({ queryKey: ["ecg", id], queryFn: () => getJson<EcgDetail>(`ecg/${id}.json`), enabled: !!id, staleTime: Infinity });
}

export function useHolter(id: string | undefined) {
  return useQuery({
    queryKey: ["holter", id],
    enabled: !!id,
    staleTime: Infinity,
    queryFn: async () => {
      const [detail, buf] = await Promise.all([
        getJson<HolterDetail>(`holter/${id}.json`),
        fetch(`${BASE}/holter/${id}.i16`).then((r) => {
          if (!r.ok) throw new Error(`holter signal: HTTP ${r.status}`);
          return r.arrayBuffer();
        }),
      ]);
      return { detail, signal: int16ToMv(new Int16Array(buf)) };
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
