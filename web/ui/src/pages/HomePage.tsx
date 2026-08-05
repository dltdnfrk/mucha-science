import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Textarea } from "../components/ui/textarea";

export default function HomePage() {
  const [topic, setTopic] = useState("");
  const navigate = useNavigate();

  const canSubmit = topic.trim().length > 0;

  const handleSubmit = () => {
    if (!canSubmit) return;
    navigate("/interview", { state: { topic: topic.trim() } });
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center gap-6 p-6">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>MUNI lab</CardTitle>
          <CardDescription>
            Studio에서 Goal과 Unknown을 정리하고 Browser에서 Evidence, Run, Report를 확인합니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            placeholder="조사하고 싶은 주제를 입력하세요. 예: '신규 진입자가 기존 시장을 재편하는 패턴과 근거'"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            className="min-h-[200px]"
          />
        </CardContent>
        <CardFooter className="justify-end">
          <Button onClick={handleSubmit} disabled={!canSubmit} size="lg">
            인터뷰 시작
          </Button>
        </CardFooter>
      </Card>

      <Card className="w-full">
        <CardHeader>
          <CardTitle>Scientific cycle (beta)</CardTitle>
          <CardDescription>
            가설을 만들고 외부 실험으로 넘기는 과학적 검토 경로입니다. 실험 수행과 결과
            검증의 책임은 사람에게 있으며, 물리적 작업은 이 도구 밖에서 이루어집니다.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Creator authority is operator-asserted and unverified. This beta can prepare an
            export package; it does not operate a lab or claim institutional approval.
          </p>
        </CardContent>
        <CardFooter className="justify-end">
          <Button variant="outline" onClick={() => navigate("/scientific")}>
            Scientific cycle (beta) 열기
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
