export type Translate = (text: string) => string;

type FailureCopy = {
  title: string;
  message: string;
  guidance?: string;
};

const FAILURE_COPY: Record<string, FailureCopy> = {
  analysis_error: {
    title: "TEXT CHECK INCOMPLETE",
    message: "The page was drawn successfully, but its lettering check could not be completed.",
    guidance: "Retry the text check. This reuses the existing page and does not redraw it.",
  },
  provider_blocked: {
    title: "WE COULDN'T DRAW THIS PAGE",
    message: "The image provider declined this scene but did not say which detail caused it. Your page plan is unchanged.",
    guidance: "A less graphic version keeps the page plan, exact lettering, and required identity references. Review the result before continuing.",
  },
  rate_limited: {
    title: "IMAGE SERVICE BUSY",
    message: "The image service has temporarily reached its quota. Wait for quota to reset and retry; your prompt does not need editing.",
  },
  shape_mismatch: {
    title: "WRONG FRAME SHAPE",
    message: "The image service returned the wrong frame shape, so we could not use this image. Review the failure and try again.",
  },
  timed_out: {
    title: "IMAGE SERVICE TIMED OUT",
    message: "The image service took too long to respond. Check whether the image finished before retrying.",
  },
  service_unavailable: {
    title: "IMAGE SERVICE UNAVAILABLE",
    message: "We could not reach the image service. Check your connection and try again.",
  },
  configuration_error: {
    title: "IMAGE SETUP ERROR",
    message: "The image service is not configured correctly for this project. Try again later or contact support if it continues.",
  },
  empty_response: {
    title: "NO IMAGE RETURNED",
    message: "The image service finished without returning an image. Try again; if it repeats, contact support.",
  },
  generation_error: {
    title: "IMAGE GENERATION FAILED",
    message: "The image service returned an unexpected error. Try again; if it keeps happening, contact support.",
  },
};

export function getImageFailureCopy(
  t: Translate,
  classification?: string | null,
  serverMessage?: string | null,
  localError?: string | null,
): FailureCopy {
  const known = classification ? FAILURE_COPY[classification] : undefined;
  if (known) {
    return {
      title: t(known.title),
      message: t(known.message),
      guidance: known.guidance ? t(known.guidance) : undefined,
    };
  }

  return {
    title: t("IMAGE GENERATION FAILED"),
    message: serverMessage?.trim() || localError?.trim() || t(
      "The image service returned an unexpected error. Try again; if it keeps happening, contact support.",
    ),
  };
}
