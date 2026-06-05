"""백엔드 실행: quality-review-api  (기본 0.0.0.0:8800)."""

import os


def main():
    import uvicorn

    uvicorn.run(
        "chandra_api.app:app",
        host=os.environ.get("QR_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("QR_API_PORT", "8800")),
        reload=False,
    )


if __name__ == "__main__":
    main()
