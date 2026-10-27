/** Which leads show a finding — used by "Show on ECG" to point the reader at the evidence. */
const MAP: [RegExp, string[]][] = [
  [/^(IMI|ISCIN|INJIN)$/, ["II", "III", "AVF"]],
  [/^(ASMI|ISCAS|INJAS)$/, ["V1", "V2", "V3"]],
  [/^(AMI|ISCAN|INJAL)$/, ["V2", "V3", "V4"]],
  [/^(ALMI|ISCAL|LMI|ISCLA)$/, ["I", "AVL", "V5", "V6"]],
  [/^(ILMI|ISCIL|IPLMI|IPMI)$/, ["II", "III", "AVF", "V5", "V6"]],
  [/^PMI$/, ["V1", "V2"]],
  [/^(LVH|HVOLT)$/, ["AVL", "V1", "V5", "V6"]],
  [/^(RVH|RAO\/RAE)$/, ["II", "V1"]],
  [/^(CLBBB|ILBBB)$/, ["I", "V1", "V6"]],
  [/^(CRBBB|IRBBB)$/, ["V1", "V2", "V6"]],
  [/^(LAFB|LPFB)$/, ["I", "II", "AVF"]],
  [/^(AFIB|AFLT|SARRH|SVTAC|PSVT|SBRAD|STACH|SR|1AVB|2AVB|3AVB|PAC|PVC|BIGU|TRIGU|WPW|LNGQT|PACE)$/, ["II", "V1"]],
  [/^(LOWT|LVOLT)$/, ["I", "II", "III", "AVR", "AVL", "AVF"]],
];

export function leadsFor(code: string): string[] {
  for (const [re, leads] of MAP) if (re.test(code)) return leads;
  return [];
}
