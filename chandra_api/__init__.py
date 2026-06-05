"""품질검토 웹서비스 백엔드(FastAPI).

현재 파이프라인(chandra.pipeline.run_quality_review)을 잡 기반 비동기 REST API로 노출한다.
인증(JWT) + 업로드→잡→폴링 구조. React(Tailwind/shadcn) 프런트가 소비한다.
"""
