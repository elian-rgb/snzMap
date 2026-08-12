import Papa from 'papaparse';

type CSVRow = Record<string, string>;

/**
 * Fetches a CSV from a URL and parses it.
 * ACS Census files have TWO header rows: the first (row index 0 in results.data)
 * is the label row ("Geography", "Geographic Area Name", ...) and should be dropped.
 * Skips rows where all values are blank.
 */
export function parseCSVFromUrl(url: string): Promise<CSVRow[]> {
  return new Promise((resolve, reject) => {
    Papa.parse<CSVRow>(url, {
      download: true,
      header: true,
      skipEmptyLines: true,
      complete(results) {
        // Filter out the ACS label row — it has GEO_ID value "Geography"
        const rows = (results.data as CSVRow[]).filter(
          (row) => row['GEO_ID'] !== 'Geography' && row['NAME'] !== 'Geographic Area Name'
        );
        resolve(rows);
      },
      error(err) {
        reject(err);
      },
    });
  });
}

/**
 * Parses a File object (user upload).
 * Skips rows where all values are blank.
 */
export function parseCSVFromFile(file: File): Promise<CSVRow[]> {
  return new Promise((resolve, reject) => {
    Papa.parse<CSVRow>(file, {
      header: true,
      skipEmptyLines: true,
      complete(results) {
        resolve(results.data as CSVRow[]);
      },
      error(err) {
        reject(err);
      },
    });
  });
}

/**
 * Streaming parse for large files. Calls onRow for each parsed data row,
 * calls onComplete when done. Skips the ACS label row automatically.
 */
export function parseCSVFromUrlStreaming(
  url: string,
  onRow: (row: CSVRow) => void,
  onComplete: () => void,
  onError: (err: Error) => void
): void {
  let firstDataRow = true;
  Papa.parse<CSVRow>(url, {
    download: true,
    header: true,
    skipEmptyLines: true,
    step(result) {
      const row = result.data as CSVRow;
      // Skip ACS label row
      if (firstDataRow) {
        firstDataRow = false;
        if (row['GEO_ID'] === 'Geography') return;
      }
      onRow(row);
    },
    complete() {
      onComplete();
    },
    error(err) {
      onError(err as unknown as Error);
    },
  });
}
