export type Translate = (text: string) => string;

type FailureCopy = {
  title: string;
  message: string;
};

const FAILURE_COPY: Record<string, { title: string; message: string }> = {
  provider_blocked: {
    title: "IMAGE REQUEST BLOCKED",
    message: "The image service rejected this request for safety reasons. Edit the prompt to remove the blocked content, then try again.",
  },
  rate_limited: {
    title: "IMAGE SERVICE BUSY",
    message: "The image service has temporarily reached its quota. Wait for quota to reset and retry; your prompt does not need editing.",
  },
  shape_mismatch: {
    title: "WRONG FRAME SHAPE",
    message: "The image service returned the wrong frame shape, so we could not use this image. Try this panel again.",
  },
  timed_out: {
    title: "IMAGE SERVICE TIMED OUT",
    message: "The image service took too long to respond. Try this panel again.",
  },
  service_unavailable: {
    title: "IMAGE SERVICE UNAVAILABLE",
    message: "We could not reach the image service. Check your connection and try this panel again.",
  },
  configuration_error: {
    title: "IMAGE SETUP ERROR",
    message: "The image service is not configured correctly for this project. Try again later or contact support if it continues.",
  },
  empty_response: {
    title: "NO IMAGE RETURNED",
    message: "The image service finished without returning an image. Try this panel again; if it repeats, try a different image model.",
  },
  generation_error: {
    title: "IMAGE GENERATION FAILED",
    message: "The image service returned an unexpected error. Try this panel again; if it keeps happening, try a different image model.",
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
    };
  }

  return {
    title: t("IMAGE GENERATION FAILED"),
    message: serverMessage?.trim() || localError?.trim() || t(
      "The image service returned an unexpected error. Try this panel again; if it keeps happening, contact support.",
    ),
  };
}
