import { useState, useCallback } from "react";
import { Search, FileText, Download, Loader2, ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const API_BASE = "/api";

const STATES = [
  { value: "", label: "Alle Landesverbände" },
  { value: "berlin", label: "Berlin" },
  { value: "brandenburg", label: "Brandenburg" },
  { value: "hamburg", label: "Hamburg" },
  { value: "rlp", label: "Rheinland-Pfalz" },
  { value: "bayern", label: "Bayern" },
  { value: "schleswig_holstein", label: "Schleswig-Holstein" },
  { value: "bund", label: "Bund" },
  { value: "niedersachsen", label: "Niedersachsen" },
  { value: "thueringen", label: "Thüringen" },
];

interface SearchResult {
  doc_id: string;
  score: number;
  kuerzel: string;
  title: string;
  year: number | null;
  status: string;
  submitter_type: string;
  landesverband: string;
  snippet: string;
}

interface MotionDetail {
  kuerzel: string;
  title: string;
  year: number | null;
  status: string | null;
  submitter: string | null;
  landesverband: string | null;
  veranstaltung: string | null;
  tags: string[] | string | null;
  text: string | null;
}

interface RAGResponse {
  answer: string;
  sources: Array<{
    kuerzel: string;
    year: number | null;
    title: string;
    status: string;
  }>;
}

function StatusBadge({ status }: { status: string }) {
  if (!status) return null;
  const s = status.toLowerCase();
  const variant = s.includes("angenommen") || s.includes("beschlossen")
    ? "default"
    : s.includes("abgelehnt") || s.includes("zurückgezogen")
    ? "destructive"
    : "secondary";
  return <Badge variant={variant} className="text-xs">{status}</Badge>;
}

function StateLabel({ value }: { value: string }) {
  const state = STATES.find((s) => s.value === value);
  return <span>{state?.label ?? value}</span>;
}

export default function SearchApp() {
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [yearMin, setYearMin] = useState("");
  const [yearMax, setYearMax] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [showFilters, setShowFilters] = useState(false);

  // Detail view
  const [selectedMotion, setSelectedMotion] = useState<MotionDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // RAG
  const [ragQuery, setRagQuery] = useState("");
  const [ragState, setRagState] = useState("");
  const [ragResult, setRagResult] = useState<RAGResponse | null>(null);
  const [ragLoading, setRagLoading] = useState(false);

  const doSearch = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    setSearched(true);
    setSelectedMotion(null);
    try {
      const params = new URLSearchParams({ q: query, mode, top_k: "20" });
      if (state) params.set("landesverband", state);
      if (yearMin) params.set("year_min", yearMin);
      if (yearMax) params.set("year_max", yearMax);
      const resp = await fetch(`${API_BASE}/search?${params}`);
      if (!resp.ok) throw new Error(await resp.text());
      const data: SearchResult[] = await resp.json();
      // Deduplicate by kuerzel
      const seen = new Set<string>();
      setResults(
        data.filter((r) => {
          if (seen.has(r.kuerzel)) return false;
          seen.add(r.kuerzel);
          return true;
        })
      );
    } catch (e) {
      console.error(e);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, state, yearMin, yearMax, mode]);

  const showMotion = useCallback(async (kuerzel: string) => {
    setDetailLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/motion/${encodeURIComponent(kuerzel)}`);
      if (!resp.ok) throw new Error(await resp.text());
      setSelectedMotion(await resp.json());
    } catch (e) {
      console.error(e);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const doRAG = useCallback(async () => {
    if (!ragQuery.trim()) return;
    setRagLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/rag`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: ragQuery,
          landesverband: ragState || null,
        }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      setRagResult(await resp.json());
    } catch (e) {
      console.error(e);
    } finally {
      setRagLoading(false);
    }
  }, [ragQuery, ragState]);

  const exportCSV = useCallback(() => {
    if (!results.length) return;
    const header = "Score,Kürzel,Jahr,Titel,Land,Status,Auszug\n";
    const rows = results.map((r) =>
      [r.score, r.kuerzel, r.year ?? "", `"${r.title}"`, r.landesverband, r.status, `"${r.snippet.slice(0, 200)}"`].join(",")
    );
    const blob = new Blob([header + rows.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "spd-antraege-export.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, [results]);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card">
        <div className="container mx-auto px-4 py-6 text-center">
          <h1 className="text-3xl font-bold tracking-tight">
            SPD Antragskorpus
          </h1>
          <p className="mt-2 text-muted-foreground">
            48.000+ Parteitagsanträge aus 16 Landesverbänden durchsuchen
          </p>
        </div>
      </header>

      <main className="container mx-auto max-w-5xl px-4 py-8">
        <Tabs defaultValue="search" className="space-y-6">
          <TabsList className="grid w-full max-w-md mx-auto grid-cols-3">
            <TabsTrigger value="search">Suche</TabsTrigger>
            <TabsTrigger value="rag">Fragen (RAG)</TabsTrigger>
            <TabsTrigger value="info">Info</TabsTrigger>
          </TabsList>

          {/* --- Search Tab --- */}
          <TabsContent value="search" className="space-y-6">
            {/* Search bar */}
            <Card>
              <CardContent className="pt-6">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    doSearch();
                  }}
                  className="space-y-4"
                >
                  <div className="flex gap-3">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Mietpreisbremse, Digitalisierung, Klimaschutz..."
                        className="pl-10 h-12 text-base"
                      />
                    </div>
                    <Button type="submit" size="lg" disabled={loading} className="h-12 px-8">
                      {loading ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        "Suchen"
                      )}
                    </Button>
                  </div>

                  {/* Collapsible filters */}
                  <button
                    type="button"
                    onClick={() => setShowFilters(!showFilters)}
                    className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 transition-transform",
                        showFilters && "rotate-180"
                      )}
                    />
                    Filter
                    {(state || yearMin || yearMax || mode !== "hybrid") && (
                      <Badge variant="secondary" className="ml-1 text-xs">aktiv</Badge>
                    )}
                  </button>

                  {showFilters && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-2">
                      <Select value={state} onValueChange={setState}>
                        <SelectTrigger>
                          <SelectValue placeholder="Landesverband" />
                        </SelectTrigger>
                        <SelectContent>
                          {STATES.map((s) => (
                            <SelectItem key={s.value || "__all"} value={s.value || "__all"}>
                              {s.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>

                      <Input
                        type="number"
                        placeholder="Jahr von"
                        value={yearMin}
                        onChange={(e) => setYearMin(e.target.value)}
                      />
                      <Input
                        type="number"
                        placeholder="Jahr bis"
                        value={yearMax}
                        onChange={(e) => setYearMax(e.target.value)}
                      />

                      <Select value={mode} onValueChange={setMode}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="hybrid">Hybrid</SelectItem>
                          <SelectItem value="bm25">BM25</SelectItem>
                          <SelectItem value="vector">Semantisch</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </form>
              </CardContent>
            </Card>

            {/* Results */}
            {searched && (
              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-4">
                  <div>
                    <CardTitle className="text-lg">
                      {results.length > 0
                        ? `${results.length} Ergebnisse`
                        : "Keine Ergebnisse"}
                    </CardTitle>
                    {results.length > 0 && (
                      <CardDescription>
                        Klicke auf einen Antrag für den Volltext
                      </CardDescription>
                    )}
                  </div>
                  {results.length > 0 && (
                    <Button variant="outline" size="sm" onClick={exportCSV}>
                      <Download className="h-4 w-4 mr-1" />
                      CSV
                    </Button>
                  )}
                </CardHeader>
                {results.length > 0 && (
                  <CardContent className="p-0">
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-16">Score</TableHead>
                            <TableHead>Kürzel</TableHead>
                            <TableHead className="w-14">Jahr</TableHead>
                            <TableHead>Titel</TableHead>
                            <TableHead className="w-24">Land</TableHead>
                            <TableHead className="w-28">Status</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {results.map((r) => (
                            <TableRow
                              key={r.doc_id}
                              className="cursor-pointer hover:bg-muted/50"
                              onClick={() => showMotion(r.kuerzel)}
                            >
                              <TableCell className="font-mono text-xs text-muted-foreground">
                                {r.score.toFixed(2)}
                              </TableCell>
                              <TableCell className="font-medium text-sm">
                                {r.kuerzel}
                              </TableCell>
                              <TableCell className="text-sm">{r.year ?? ""}</TableCell>
                              <TableCell className="text-sm max-w-xs truncate">
                                {r.title}
                              </TableCell>
                              <TableCell className="text-sm">
                                <StateLabel value={r.landesverband} />
                              </TableCell>
                              <TableCell>
                                <StatusBadge status={r.status} />
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </CardContent>
                )}
              </Card>
            )}

            {/* Motion detail */}
            {detailLoading && (
              <Card>
                <CardContent className="flex items-center justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </CardContent>
              </Card>
            )}
            {selectedMotion && !detailLoading && (
              <Card>
                <CardHeader>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <CardTitle>{selectedMotion.title}</CardTitle>
                      <CardDescription className="mt-1">
                        {selectedMotion.kuerzel}
                      </CardDescription>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setSelectedMotion(null)}
                    >
                      Schließen
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-2 mt-3">
                    {selectedMotion.year && (
                      <Badge variant="outline">{selectedMotion.year}</Badge>
                    )}
                    {selectedMotion.landesverband && (
                      <Badge variant="outline">
                        <StateLabel value={selectedMotion.landesverband} />
                      </Badge>
                    )}
                    {selectedMotion.status && (
                      <StatusBadge status={selectedMotion.status} />
                    )}
                    {selectedMotion.submitter && (
                      <Badge variant="secondary">{selectedMotion.submitter}</Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="prose prose-sm max-w-none dark:prose-invert whitespace-pre-wrap">
                    {selectedMotion.text || "Kein Text verfügbar."}
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* --- RAG Tab --- */}
          <TabsContent value="rag" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Fragen an den Antragskorpus</CardTitle>
                <CardDescription>
                  Stelle eine Frage und erhalte eine KI-gestützte Antwort mit
                  Quellenbelegen aus dem Antragskorpus.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    doRAG();
                  }}
                  className="space-y-4"
                >
                  <div className="flex gap-3">
                    <Input
                      value={ragQuery}
                      onChange={(e) => setRagQuery(e.target.value)}
                      placeholder="z.B. Was hat die SPD Berlin zu Mieten beschlossen?"
                      className="h-12 text-base"
                    />
                    <Button type="submit" size="lg" disabled={ragLoading} className="h-12 px-8">
                      {ragLoading ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        "Fragen"
                      )}
                    </Button>
                  </div>
                  <Select value={ragState} onValueChange={setRagState}>
                    <SelectTrigger className="w-64">
                      <SelectValue placeholder="Landesverband (optional)" />
                    </SelectTrigger>
                    <SelectContent>
                      {STATES.map((s) => (
                        <SelectItem key={s.value || "__all"} value={s.value || "__all"}>
                          {s.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </form>
              </CardContent>
            </Card>

            {ragResult && (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">Antwort</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="prose prose-sm max-w-none dark:prose-invert whitespace-pre-wrap">
                      {ragResult.answer}
                    </div>
                  </CardContent>
                </Card>

                {ragResult.sources.length > 0 && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Quellen</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ul className="space-y-2">
                        {ragResult.sources.map((s) => (
                          <li
                            key={s.kuerzel}
                            className="flex items-center gap-2 text-sm"
                          >
                            <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                            <span className="font-medium">{s.kuerzel}</span>
                            {s.year && (
                              <span className="text-muted-foreground">
                                ({s.year})
                              </span>
                            )}
                            <span className="text-muted-foreground truncate">
                              {s.title}
                            </span>
                            <StatusBadge status={s.status} />
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                )}
              </>
            )}
          </TabsContent>

          {/* --- Info Tab --- */}
          <TabsContent value="info">
            <Card>
              <CardHeader>
                <CardTitle>Über dieses Tool</CardTitle>
              </CardHeader>
              <CardContent className="prose prose-sm max-w-none dark:prose-invert">
                <p>
                  Hybride Suchpipeline: <strong>BM25</strong> (Schlüsselwort) +{" "}
                  <strong>Embedding</strong> (semantisch) +{" "}
                  <strong>Reciprocal Rank Fusion</strong>.
                </p>
                <table>
                  <tbody>
                    <tr>
                      <td className="font-medium">Dokumente</td>
                      <td>48.000+</td>
                    </tr>
                    <tr>
                      <td className="font-medium">Landesverbände</td>
                      <td>16</td>
                    </tr>
                    <tr>
                      <td className="font-medium">Zeitraum</td>
                      <td>2010 — 2025</td>
                    </tr>
                    <tr>
                      <td className="font-medium">Suchmodi</td>
                      <td>hybrid, bm25, vector</td>
                    </tr>
                  </tbody>
                </table>
                <p>
                  <strong>Funktionen:</strong> Volltextsuche, Dokumentansicht,
                  RAG-Fragen mit Quellenbelegen, CSV-Export.
                </p>
                <p>
                  <a
                    href="https://github.com/spd-antraege/spd_antraege"
                    target="_blank"
                    rel="noopener"
                  >
                    Quellcode auf GitHub
                  </a>
                </p>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>

      <footer className="border-t py-6 text-center text-sm text-muted-foreground">
        <p>
          SPD Antragskorpus — Daten aus den Antragsportalen der
          SPD-Landesverbände und PDF-Antragsbüchern (2010–2025)
        </p>
      </footer>
    </div>
  );
}
