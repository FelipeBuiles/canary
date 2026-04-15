import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { pagePreviewUrl } from "../api";
export function PagePreview({ project, pageNum }) {
    return (_jsxs("div", { children: [_jsxs("h3", { style: { fontSize: 14, marginBottom: 8 }, children: ["Page ", pageNum, " Preview"] }), _jsx("iframe", { src: pagePreviewUrl(project, pageNum), style: {
                    width: "100%",
                    height: 700,
                    border: "1px solid #ddd",
                    borderRadius: 4,
                }, title: `Page ${pageNum} preview` })] }));
}
