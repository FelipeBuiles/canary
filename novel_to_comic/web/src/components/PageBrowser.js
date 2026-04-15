import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { listPages, pageThumbnailUrl } from "../api";
import { PagePreview } from "./PagePreview";
export function PageBrowser({ project }) {
    const [pages, setPages] = useState([]);
    const [selectedPage, setSelectedPage] = useState(null);
    useEffect(() => {
        listPages(project).then((p) => {
            setPages(p);
            setSelectedPage(null);
        }).catch(console.error);
    }, [project]);
    if (pages.length === 0) {
        return (_jsxs("div", { children: [_jsx("h2", { style: { fontSize: 16, marginBottom: 8 }, children: "Pages" }), _jsx("p", { style: { color: "#888", fontSize: 14 }, children: "No pages yet. Run stages through \"assemble\" first." })] }));
    }
    return (_jsxs("div", { children: [_jsxs("h2", { style: { fontSize: 16, marginBottom: 8 }, children: ["Pages", _jsxs("span", { style: { fontWeight: 400, color: "#888", marginLeft: 8, fontSize: 13 }, children: [pages.length, " pages"] })] }), _jsx("div", { style: {
                    display: "flex",
                    gap: 8,
                    overflowX: "auto",
                    paddingBottom: 8,
                    marginBottom: 16,
                }, children: pages.map((p) => (_jsxs("div", { onClick: () => setSelectedPage(p.page_number), style: {
                        cursor: "pointer",
                        border: selectedPage === p.page_number ? "2px solid #3b82f6" : "2px solid #ddd",
                        borderRadius: 4,
                        padding: 2,
                        flexShrink: 0,
                    }, children: [_jsx("img", { src: pageThumbnailUrl(project, p.page_number), alt: `Page ${p.page_number}`, style: { width: 80, height: 113, objectFit: "cover", display: "block" } }), _jsx("div", { style: { fontSize: 11, textAlign: "center", padding: 2, color: "#666" }, children: p.page_number })] }, p.page_number))) }), selectedPage && _jsx(PagePreview, { project: project, pageNum: selectedPage })] }));
}
