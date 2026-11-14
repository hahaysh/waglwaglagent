import type { ChatAttachment } from "./api";

export const attachmentAccept = ".png,.jpg,.jpeg,.webp,.txt,.md,.csv,.json,.log,.py,.js,.ts,.tsx,.jsx,.html,.css,.yaml,.yml,.xml,.sql,.sh,.ps1";
const textExtensions = new Set(attachmentAccept.split(",").slice(4));
const images: Record<string, string> = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };

export function attachmentBytes(file: ChatAttachment): number {
  return file.data.length * 3 / 4 - (file.data.endsWith("==") ? 2 : file.data.endsWith("=") ? 1 : 0);
}

export async function readAttachments(files: File[], current: ChatAttachment[]): Promise<ChatAttachment[]> {
  if (current.length + files.length > 3) throw new Error("첨부는 한 메시지에 최대 3개입니다.");
  if (current.reduce((sum, file) => sum + attachmentBytes(file), 0)
    + files.reduce((sum, file) => sum + file.size, 0) > 4 * 1024 * 1024) {
    throw new Error("첨부 파일의 합계는 4MB 이하여야 합니다.");
  }
  const added = await Promise.all(files.map(async (file): Promise<ChatAttachment> => {
    const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    const mime = images[extension] || (textExtensions.has(extension) ? "text/plain" : "");
    if (!mime) throw new Error("PNG·JPEG·WebP 또는 UTF-8 텍스트·코드 파일만 지원합니다. PDF·Word·압축 파일은 아직 지원하지 않습니다.");
    if (!file.size || file.size > (mime === "text/plain" ? 32768 : 2 * 1024 * 1024)) {
      throw new Error("이미지는 파일당 2MB, 텍스트·코드는 32KB 이하의 빈 파일이 아닌 파일을 첨부해주세요.");
    }
    if (file.name.length > 120 || /[\u0000-\u001f/\\:]/.test(file.name)) {
      throw new Error("파일 이름은 경로·제어 문자 없이 120자 이하여야 합니다.");
    }
    const data = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => typeof reader.result === "string"
        ? resolve(reader.result.split(",", 2)[1]) : reject(new Error("파일을 읽지 못했습니다."));
      reader.onerror = () => reject(new Error("파일을 읽지 못했습니다. 다시 첨부해주세요."));
      reader.onabort = () => reject(new Error("파일 읽기가 취소됐습니다."));
      reader.readAsDataURL(file);
    });
    return { name: file.name, mime_type: mime, data };
  }));
  return [...current, ...added];
}
