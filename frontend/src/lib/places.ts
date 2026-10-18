// Where else to look. Links only: these sites are opened in your browser, never searched by the app.

export const KINDS = [
  { code: "job", label: "Jobs", word: "" },
  { code: "werkstudent", label: "Werkstudent", word: "Werkstudent" },
  { code: "praktikum", label: "Praktikum / internship", word: "Praktikum" },
  { code: "abschlussarbeit", label: "Abschlussarbeit / thesis", word: "Abschlussarbeit" },
] as const;

export const KIND_LABEL: Record<string, string> = {
  werkstudent: "Werkstudent", praktikum: "Praktikum", abschlussarbeit: "Thesis", job: "Job",
};

// Official career portals (checked by hand). Audi hires through the Volkswagen Group portal.
export const CAREER_PAGES: Record<string, string> = {
  "BMW": "https://www.bmwgroup.jobs/de/de/jobfinder.html",
  "Mercedes-Benz": "https://jobs.mercedes-benz.com",
  "Bosch": "https://jobs.bosch.com/en/?pages=1&country=de",
  "Siemens": "https://jobs.siemens.com/en_US/externaljobs/SearchJobs",
  "Porsche": "https://jobs.porsche.com/index.php?ac=search_result",
  "Volkswagen": "https://jobs.volkswagen-group.com/search/",
  "Audi": "https://jobs.volkswagen-group.com/search/",
  "SAP": "https://jobs.sap.com/en/jobs/",
  "Infineon": "https://www.infineon.com/careers",
  "Continental": "https://jobs.continental.com/en/",
  "ZF": "https://jobs.zf.com/",
};
export const SUGGESTED_COMPANIES = Object.keys(CAREER_PAGES);

export function careerPage(company: string): string | null {
  const key = Object.keys(CAREER_PAGES).find((k) => k.toLowerCase() === company.trim().toLowerCase());
  return key ? CAREER_PAGES[key] : null;
}

const slug = (s: string) => s.trim().toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
  .replace(/ß/g, "ss").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

export function jobSiteLinks(query: string, city: string, radiusKm: number) {
  const q = encodeURIComponent(query.trim());
  const l = encodeURIComponent(city.trim());
  return [
    { name: "Indeed", url: `https://de.indeed.com/jobs?q=${q}${city ? `&l=${l}&radius=${radiusKm}` : ""}` },
    { name: "LinkedIn", url: `https://www.linkedin.com/jobs/search/?keywords=${q}${city ? `&location=${l}` : "&location=Germany"}` },
    { name: "StepStone", url: `https://www.stepstone.de/jobs/${slug(query) || "it"}${city ? `/in-${slug(city)}?radius=${radiusKm}` : ""}` },
    { name: "XING", url: `https://www.xing.com/jobs/search?keywords=${q}${city ? `&location=${l}` : ""}` },
    { name: "Bundesagentur (website)", url: `https://www.arbeitsagentur.de/jobsuche/suche?was=${q}${city ? `&wo=${l}&umkreis=${radiusKm}` : ""}` },
  ];
}
